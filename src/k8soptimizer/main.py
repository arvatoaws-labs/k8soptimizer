"""
This is a skeleton file that can serve as a starting point for a Python
console script. To run this script uncomment the following lines in the
``[options.entry_points]`` section in ``setup.cfg``::

    console_scripts =
         fibonacci = k8soptimizer.main:run

Then run ``pip install .`` (or ``pip install -e .`` for editable mode)
which will install the command ``fibonacci`` inside your current environment.

Besides console scripts, the header (i.e. until ``_logger``...) of this file can
also be used as template for Python modules.

Note:
    This file can be renamed depending on your needs or safely removed if not needed.

References:
    - https://setuptools.pypa.io/en/latest/userguide/entry_point.html
    - https://pip.pypa.io/en/stable/reference/pip_install
"""

import argparse
import json
import logging
import os
import re
import sys
from typing import Optional

import requests
from beartype import beartype
from kubernetes import client, config
from kubernetes.client.models import (
    V1Container,
    V1Deployment,
    V1DeploymentList,
    V1NamespaceList,
    V2HorizontalPodAutoscaler,
)

from k8soptimizer import __version__, helpers

__author__ = "Philipp Hellmich"
__copyright__ = "Arvato Systems GmbH"
__license__ = "MIT"

__domain__ = "arvato-aws.io"

_logger = logging.getLogger(__name__)


PROMETHEUS_URL = os.getenv("PROMETHEUS_URL", "http://localhost:9090")

NAMESPACE_PATTERN = os.getenv("NAMESPACE_PATTERN", ".*")
DEPLOYMENT_PATTERN = os.getenv("DEPLOYMENT_PATTERN", ".*")
CONTAINER_PATTERN = os.getenv("CONTAINER_PATTERN", ".*")

# in minutes
CREATE_AGE_THRESHOLD = int(os.getenv("CREATE_AGE_THRESHOLD", 60))
# cannot not be less than 5 minutes)
UPDATE_AGE_THRESHOLD = int(os.getenv("UPDATE_AGE_THRESHOLD", 60))
MIN_LOOKBACK_MINUTES = int(os.getenv("MIN_LOOKBACK_MINUTES", 5))
MAX_LOOKBACK_MINUTES = int(os.getenv("MIN_LOOKBACK_MINUTES", 3600 * 24 * 30))
OFFSET_LOOKBACK_MINUTES = int(os.getenv("OFFSET_LOOKBACK_MINUTES", 5))
DEFAULT_LOOKBACK_MINUTES = int(os.getenv("DEFAULT_LOOKBACK_MINUTES", 3600 * 24 * 7))
DEFAULT_QUANTILE_OVER_TIME = float(os.getenv("DEFAULT_QUANTILE_OVER_TIME", 0.95))

# operating mode
DRY_RUN_MODE = float(os.getenv("DRY_RUN_MODE", False))

MIN_CPU_REQUEST = float(os.getenv("MIN_CPU_REQUEST", 0.001))
MAX_CPU_REQUEST = float(os.getenv("MAX_CPU_REQUEST", 16))
MAX_CPU_REQUEST_NODEJS = 1.0
MIN_MEMORY_REQUEST = int(os.getenv("MIN_MEMORY_REQUEST", 1024**2 * 16))
MAX_MEMORY_REQUEST = int(os.getenv("MAX_MEMORY_REQUEST", 1024**3 * 16))
MIN_MEMORY_LIMIT = int(os.getenv("MIN_MEMORY_LIMIT", 1024**2 * 128))
MAX_MEMORY_LIMIT = int(os.getenv("MAX_MEMORY_LIMIT", 1024**3 * 32))
MEMORY_LIMIT_RATIO = int(os.getenv("MEMORY_LIMIT_RATIO", 1.5))

CHANGE_THRESHOLD = os.getenv("CHANGE_THRESHOLD", 0.1)

stats = {}
stats["old_cpu_sum"] = 0
stats["new_cpu_sum"] = 0
stats["old_memory_sum"] = 0
stats["new_memory_sum"] = 0

# ---- Python API ----
# The functions defined in this section can be imported by users in their
# Python scripts/interactive interpreter, e.g. via
# `from k8soptimizer.skeleton import fib`,
# when using this Python module as a library.


@beartype
def query_prometheus(query: str) -> dict:
    """
    Query Prometheus API with the specified query string.

    Args:
        query (str): The Prometheus query string.

    Returns:
        dict: The JSON response from the Prometheus API.

    Raises:
        RuntimeError: If the response is missing expected data fields.

    Example:
        response = query_prometheus('sum(rate(http_requests_total{job="api"}[5m]))')
    """
    _logger.debug(query)
    response = requests.get(PROMETHEUS_URL + "/api/v1/query", params={"query": query})
    j = json.loads(response.text)
    _logger.debug(j)
    if "data" not in j:
        raise RuntimeError("Got invalid results from query: {}".format(query))
    if "result" not in j["data"]:
        raise RuntimeError("Got invalid results from query: {}".format(query))
    return j


@beartype
def verify_prometheus_connection() -> bool:
    """
    Verify connection to the Prometheus API.

    Returns:
        bool: True if the connection is successful, False otherwise.

    Raises:
        RuntimeError: If the response is missing expected data fields or the connection fails.

    Example:
        connection_successful = verify_prometheus_connection()
    """
    response = requests.get(PROMETHEUS_URL + "/api/v1/status/buildinfo")
    j = json.loads(response.text)
    _logger.debug(j)
    if "status" not in j:
        raise RuntimeError("Got invalid results request: {}".format(response.text))
    if j["status"] == "success":
        return True
    raise RuntimeError("Connection to prometheus api failed")


@beartype
def verify_kubernetes_connection() -> bool:
    """
    Verify connection to the Kubernetes API.

    Returns:
        bool: True if the connection is successful, False otherwise.

    Raises:
        RuntimeError: If the connection to the Kubernetes API fails or if there is a configuration error.

    Example:
        connection_successful = verify_kubernetes_connection()
    """
    try:
        config.load_kube_config()
        client.ApisApi().get_api_versions_with_http_info()
    except (config.exceptions.ConfigException, client.exceptions.ApiException):
        raise RuntimeError("Connection to kubernetes api failed")
    return True


@beartype
def get_max_cpu_cores_per_runtime(runtime: str) -> int:
    """
    Get the maximum number of CPU cores allowed per runtime.

    Args:
        runtime (str): The name of the runtime.

    Returns:
        int: The maximum number of CPU cores.

    Example:
        max_cores = get_max_cpu_cores_per_runtime("nodejs")
    """
    if runtime == "nodejs":
        return 1
    return 100


@beartype
def get_number_of_samples_from_history(
    namespace: str,
    workload: str,
    workload_type: str = "deployment",
    lookback_minutes: int = DEFAULT_LOOKBACK_MINUTES,
) -> float:
    """
    Get the CPU cores usage history for a specific container.

    Args:
        namespace (str): The name of the Kubernetes namespace.
        workload (str): The name of the workload (e.g., deployment).
        workload_type (str, optional): The type of workload. Default is "deployment".
        lookback_minutes (int, optional): The number of minutes to look back in time for the query. Default is DEFAULT_LOOKBACK_MINUTES.

    Returns:
        float: The number of samples from prometheus.

    Raises:
        RuntimeError: If no data is found for the Prometheus query.

    Example:
        samples = get_number_of_samples_from_history("my-namespace", "my-deployment")
    """
    query = 'max by (namespace,workload,workload_type) (count_over_time(kube_workload_container_resource_usage_cpu_cores_avg{{namespace="{namespace}", workload="{workload}", workload_type="{workload_type}"}}[{lookback_minutes}m]))'.format(
        namespace=namespace,
        workload=workload,
        workload_type=workload_type,
        lookback_minutes=lookback_minutes,
    )
    j = query_prometheus(query)

    if j["data"]["result"] == []:
        raise RuntimeError("No data found for prometheus query: {}".format(query))
    return float(j["data"]["result"][0]["value"][1])


# FIXME make avg
@beartype
def get_max_pods_per_deployment_history(
    namespace_name: str,
    deployment_name: str,
    lookback_minutes: int = DEFAULT_LOOKBACK_MINUTES,
    quantile_over_time: float = DEFAULT_QUANTILE_OVER_TIME,
) -> int:
    """
    Get the maximum number of pods for a deployment based on historical data.

    Args:
        namespace_name (str): The name of the Kubernetes namespace.
        deployment_name (str): The name of the deployment.
        lookback_minutes (int, optional): The number of minutes to look back in time for the query. Default is DEFAULT_LOOKBACK_MINUTES.
        quantile_over_time (float, optional): The quantile value for the query. Default is DEFAULT_QUANTILE_OVER_TIME.

    Returns:
        int: The maximum number of pods.

    Raises:
        RuntimeError: If no data is found for the Prometheus query.

    Example:
        max_pods = get_max_pods_per_deployment_history("my-namespace", "my-deployment")
    """
    query = 'max(quantile_over_time({quantile_over_time}, kube_deployment_spec_replicas{{job="kube-state-metrics", namespace="{namespace_name}", deployment="{deployment_name}"}}[{lookback_minutes}m]))'.format(
        quantile_over_time=quantile_over_time,
        namespace_name=namespace_name,
        deployment_name=deployment_name,
        lookback_minutes=lookback_minutes,
    )
    j = query_prometheus(query)

    if j["data"]["result"] == []:
        raise RuntimeError("No data found for prometheus query: {}".format(query))
    return int(j["data"]["result"][0]["value"][1])


@beartype
def get_cpu_cores_usage_history(
    namespace: str,
    workload: str,
    container: str,
    workload_type: str = "deployment",
    lookback_minutes: int = DEFAULT_LOOKBACK_MINUTES,
    quantile_over_time: float = DEFAULT_QUANTILE_OVER_TIME,
) -> float:
    """
    Get the CPU cores usage history for a specific container.

    Args:
        namespace (str): The name of the Kubernetes namespace.
        workload (str): The name of the workload (e.g., deployment).
        container (str): The name of the container.
        workload_type (str, optional): The type of workload. Default is "deployment".
        lookback_minutes (int, optional): The number of minutes to look back in time for the query. Default is DEFAULT_LOOKBACK_MINUTES.
        quantile_over_time (float, optional): The quantile value for the query. Default is DEFAULT_QUANTILE_OVER_TIME.

    Returns:
        float: The CPU cores usage value.

    Raises:
        RuntimeError: If no data is found for the Prometheus query.

    Example:
        cpu_usage = get_cpu_cores_usage_history("my-namespace", "my-deployment", "my-container")
    """
    query = 'quantile_over_time({quantile_over_time}, kube_workload_container_resource_usage_cpu_cores_avg{{namespace="{namespace}", workload="{workload}", workload_type="{workload_type}", container="{container}"}}[{lookback_minutes}m])'.format(
        quantile_over_time=quantile_over_time,
        namespace=namespace,
        workload=workload,
        workload_type=workload_type,
        container=container,
        lookback_minutes=lookback_minutes,
    )
    j = query_prometheus(query)

    if j["data"]["result"] == []:
        raise RuntimeError("No data found for prometheus query: {}".format(query))
    return float(j["data"]["result"][0]["value"][1])


@beartype
def get_memory_bytes_usage_history(
    namespace: str,
    workload: str,
    container: str,
    workload_type: str = "deployment",
    lookback_minutes: int = DEFAULT_LOOKBACK_MINUTES,
    quantile_over_time: float = DEFAULT_QUANTILE_OVER_TIME,
) -> float:
    """
    Get the memory usage history (in bytes) for a specific container.

    Args:
        namespace (str): The name of the Kubernetes namespace.
        workload (str): The name of the workload (e.g., deployment).
        container (str): The name of the container.
        workload_type (str, optional): The type of workload. Default is "deployment".
        lookback_minutes (int, optional): The number of minutes to look back in time for the query. Default is DEFAULT_LOOKBACK_MINUTES.
        quantile_over_time (float, optional): The quantile value for the query. Default is DEFAULT_QUANTILE_OVER_TIME.

    Returns:
        float: The memory usage value in bytes.

    Raises:
        RuntimeError: If no data is found for the Prometheus query.

    Example:
        memory_usage = get_memory_bytes_usage_history("my-namespace", "my-deployment", "my-container")
    """
    query = 'quantile_over_time({quantile_over_time}, kube_workload_container_resource_usage_memory_bytes_max{{namespace="{namespace}", workload="{workload}", workload_type="{workload_type}", container="{container}"}}[{lookback_minutes}m])'.format(
        quantile_over_time=quantile_over_time,
        namespace=namespace,
        workload=workload,
        workload_type=workload_type,
        container=container,
        lookback_minutes=lookback_minutes,
    )
    j = query_prometheus(query)

    if j["data"]["result"] == []:
        raise RuntimeError("No data found for prometheus query: {}".format(query))
    return float(j["data"]["result"][0]["value"][1])


@beartype
def discover_container_runtime(
    namespace: str, workload: str, container: str, workload_type: str = "deployment"
) -> Optional[str]:
    """
    Discover the container runtime for a specific container.

    Args:
        namespace (str): The name of the Kubernetes namespace.
        workload (str): The name of the workload (e.g., deployment).
        container (str): The name of the container.
        workload_type (str, optional): The type of workload. Default is "deployment".

    Returns:
        Optional[str]: The name of the container runtime, or None if it couldn't be determined.

    Example:
        runtime = discover_container_runtime("my-namespace", "my-deployment", "my-container")
    """
    if is_nodejs_container(namespace, workload, container, workload_type):
        return "nodejs"
    return None


@beartype
def get_hpa_for_deployment(
    namespace_name: str, deployment_name: str
) -> Optional[V2HorizontalPodAutoscaler]:
    """
    Get the Horizontal Pod Autoscaler (HPA) associated with a specific deployment.

    Args:
        namespace_name (str): The name of the Kubernetes namespace.
        deployment_name (str): The name of the deployment.

    Returns:
        Optional[V2HorizontalPodAutoscaler]: The HPA object if found, or None if not found.

    Example:
        hpa = get_hpa_for_deployment("my-namespace", "my-deployment")
    """
    autoscaling_api = client.AutoscalingV2Api()
    for hpa in autoscaling_api.list_namespaced_horizontal_pod_autoscaler(
        namespace=namespace_name
    ).items:
        if hpa.spec.scale_target_ref.kind != "Deployment":
            continue
        if hpa.spec.scale_target_ref.name != deployment_name:
            continue
        return hpa
    return None


@beartype
def is_hpa_enabled_for_deployment(namespace_name: str, deployment_name: str) -> bool:
    """
    Check if Horizontal Pod Autoscaling (HPA) is enabled for a specific deployment.

    Args:
        namespace_name (str): The name of the Kubernetes namespace.
        deployment_name (str): The name of the deployment.

    Returns:
        bool: True if HPA is enabled, False otherwise.

    Example:
        hpa_enabled = is_hpa_enabled_for_deployment("my-namespace", "my-deployment")
    """
    return get_hpa_for_deployment(namespace_name, deployment_name) is not None


@beartype
def calculate_hpa_target_ratio(
    namespace_name: str,
    deployment_name: str,
    lookback_minutes: int = DEFAULT_LOOKBACK_MINUTES,
) -> dict:
    """
    Calculate the target ratio for Horizontal Pod Autoscaling (HPA) based on historical data.

    Args:
        namespace_name (str): The name of the Kubernetes namespace.
        deployment_name (str): The name of the deployment.
        lookback_minutes (int, optional): The number of minutes to look back in time for historical data. Default is DEFAULT_LOOKBACK_MINUTES.

    Returns:
        dict: A dictionary with target ratios for CPU and memory.

    Example:
        target_ratios = calculate_hpa_target_ratio("my-namespace", "my-deployment")
    """
    hpa_ratio_addon = 0
    hpa_min_replica = 0
    hpa_max_replica = 0
    hpa_range = 0
    target_ratio_cpu = 1.0
    target_ratio_memory = 1.0

    hpa = get_hpa_for_deployment(namespace_name, deployment_name)
    if hpa is None:
        return {"cpu": float(target_ratio_cpu), "memory": float(target_ratio_memory)}

    hpa_min_replica = hpa.spec.min_replicas
    hpa_max_replica = hpa.spec.max_replicas
    hpa_range = hpa_max_replica - hpa_min_replica
    for metric in hpa.spec.metrics:
        if metric.type != "Resource":
            continue
        if metric.resource.name == "cpu":
            hpa_target_cpu = metric.resource.target.average_utilization / 100
            target_ratio_cpu = round(1 / hpa_target_cpu, 2)
            _logger.info(
                "Changing target ratio cpu to match hpa utilization: %s"
                % target_ratio_cpu
            )
        if metric.resource.name == "memory":
            hpa_target_memory = metric.resource.target.average_utilization / 100
            target_ratio_memory = round(1 / hpa_target_memory, 2)
            _logger.info(
                "Changing target ratio memory to match hpa utilization: %s"
                % target_ratio_memory
            )

    replica_count_history = round(
        get_max_pods_per_deployment_history(
            namespace_name, deployment_name, lookback_minutes
        )
    )

    _logger.info("Hpa min repliacs: %s" % hpa_min_replica)
    _logger.info("Hpa max replicas: %s" % hpa_max_replica)
    _logger.info("Hpa avg count history: %s" % replica_count_history)

    # increase cpu request if current replica count is higher than min replica count
    if replica_count_history > hpa_min_replica and hpa_range > 0:
        _logger.info("Hpa avg range: %s" % hpa_range)
        hpa_range_position = replica_count_history - hpa_min_replica
        _logger.info("Hpa avg range position: %s" % hpa_range_position)
        hpa_ratio_addon = round((hpa_range_position) / hpa_range, 2)

    if hpa_ratio_addon > 0.5:
        _logger.info(
            "Increasing target ratio cpu due to hpa near limit: %s" % hpa_ratio_addon
        )
        target_ratio_cpu = round(target_ratio_cpu + hpa_ratio_addon, 3)

    return {"cpu": float(target_ratio_cpu), "memory": float(target_ratio_memory)}


@beartype
def calculate_cpu_requests(
    namespace_name: str,
    workload: str,
    workload_type: str,
    container_name: str,
    target_ratio_cpu: float,
    lookback_minutes: int,
) -> float:
    """
    Calculate the CPU requests for a specific container based on historical data and target ratio.

    Args:
        namespace_name (str): The name of the Kubernetes namespace.
        workload (str): The name of the workload (e.g., deployment).
        workload_type (str): The type of workload.
        container_name (str): The name of the container.
        target_ratio_cpu (float): The target ratio for CPU.
        lookback_minutes (int): The number of minutes to look back in time for historical data.

    Returns:
        float: The calculated CPU requests.

    Example:
        cpu_requests = calculate_cpu_requests("my-namespace", "my-workload", "deployment", "my-container", 1.5, 60)
    """
    new_cpu = round(
        max(
            MIN_CPU_REQUEST,
            min(
                MAX_CPU_REQUEST,
                get_cpu_cores_usage_history(
                    namespace_name,
                    workload,
                    container_name,
                    workload_type,
                    lookback_minutes,
                )
                * target_ratio_cpu,
            ),
        ),
        3,
    )
    runtime = discover_container_runtime(
        namespace_name, workload, container_name, workload_type
    )
    if runtime == "nodejs":
        new_cpu = min(MAX_CPU_REQUEST_NODEJS, new_cpu)

    return float(new_cpu)


@beartype
def calculate_memory_requests(
    namespace_name: str,
    workload: str,
    workload_type: str,
    container_name: str,
    target_ratio_memory: float,
    lookback_minutes: int,
):
    """
    Calculate the memory requests for a specific container based on historical data, target ratio, and OOM history.

    Args:
        namespace_name (str): The name of the Kubernetes namespace.
        workload (str): The name of the workload (e.g., deployment).
        workload_type (str): The type of workload.
        container_name (str): The name of the container.
        target_ratio_memory (float): The target ratio for memory.
        lookback_minutes (int): The number of minutes to look back in time for historical data.

    Returns:
        int: The calculated memory requests in bytes.

    Example:
        memory_requests = calculate_memory_requests("my-namespace", "my-workload", "deployment", "my-container", 1.5, 60)
    """
    if (
        get_oom_killed_history(
            namespace_name, workload, container_name, workload_type, lookback_minutes
        )
        > 0
    ):
        target_ratio_memory = target_ratio_memory * 2

    new_memory = round(
        max(
            MIN_MEMORY_REQUEST,
            min(
                MAX_MEMORY_REQUEST,
                get_memory_bytes_usage_history(
                    namespace_name,
                    workload,
                    container_name,
                    workload_type,
                )
                * target_ratio_memory,
            ),
        )
    )

    return int(new_memory)


@beartype
def calculate_memory_limits(
    namespace_name: str,
    workload: str,
    workload_type: str,
    container_name: str,
    memory_requests: int,
) -> int:
    """
    Calculate the memory limits for a specific container based on memory requests.

    Args:
        namespace_name (str): The name of the Kubernetes namespace.
        workload (str): The name of the workload (e.g., deployment).
        workload_type (str): The type of workload.
        container_name (str): The name of the container.
        memory_requests (int): The memory requests in bytes.

    Returns:
        int: The calculated memory limits in bytes.

    Example:
        memory_limits = calculate_memory_limits("my-namespace", "my-workload", "deployment", "my-container", 2048)
    """
    new_memory_limit = max(
        MIN_MEMORY_LIMIT,
        min(MAX_MEMORY_LIMIT, memory_requests * MEMORY_LIMIT_RATIO),
    )
    return int(new_memory_limit)


@beartype
def get_namespaces(namespace_pattern: str = ".*") -> V1NamespaceList:
    """
    Get a list of Kubernetes namespaces that match the specified pattern.

    Args:
        namespace_pattern (str, optional): A regular expression pattern to filter namespaces. Default is ".*".

    Returns:
        V1NamespaceList: A list of namespaces.

    Example:
        namespaces = get_namespaces("my-namespace.*")
    """
    core_api = client.CoreV1Api()
    resp_ns = core_api.list_namespace(watch=False)
    items = []

    for namespace in resp_ns.items:
        _logger.debug(namespace)
        namespace_name = namespace.metadata.name

        x = re.search(namespace_pattern, namespace_name)
        if x is None:
            _logger.debug(
                "Skipping namespace due to NAMESPACE_PATTERN: %s" % namespace_name
            )
            continue

        items.append(namespace)

    return V1NamespaceList(items=items)


@beartype
def get_deployments(
    namespace_name: str, deplopyment_pattern: str = ".*", only_running: bool = True
) -> V1DeploymentList:
    """
    Get a list of Kubernetes deployments in a specific namespace that match the specified pattern.

    Args:
        namespace_name (str): The name of the Kubernetes namespace.
        deplopyment_pattern (str, optional): A regular expression pattern to filter deployments. Default is ".*".
        only_running (bool, optional): Flag to include only running deployments. Default is True.

    Returns:
        V1DeploymentList: A list of deployments.

    Example:
        deployments = get_deployments("my-namespace", "my-deployment.*", only_running=True)
    """
    apis_api = client.AppsV1Api()
    resp_deploy = apis_api.list_namespaced_deployment(namespace=namespace_name)
    items = []
    for deployment in resp_deploy.items:
        _logger.debug(deployment)
        deployment_name = deployment.metadata.name

        x = re.search(deplopyment_pattern, deployment_name)
        if x is None:
            _logger.debug(
                "Skipping deployment due to DEPLOYMENT_PATTERN: %s" % deployment_name
            )
            continue

        if only_running and deployment.spec.replicas == 0:
            _logger.debug(
                "Skipping deployment due to zero replicas: %s" % deployment_name
            )
            continue

        items.append(deployment)

    return V1DeploymentList(items=items)


@beartype
def get_oom_killed_history(
    namespace: str,
    workload: str,
    container: str,
    workload_type: str = "deployment",
    lookback_minutes: int = DEFAULT_LOOKBACK_MINUTES,
) -> int:
    """
    Get the count of out-of-memory (OOM) events for a specific container based on historical data.

    Args:
        namespace (str): The name of the Kubernetes namespace.
        workload (str): The name of the workload (e.g., deployment).
        container (str): The name of the container.
        workload_type (str, optional): The type of workload. Default is "deployment".
        lookback_minutes (int, optional): The number of minutes to look back in time for historical data.
                                         Default is the value of DEFAULT_LOOKBACK_MINUTES.

    Returns:
        int: The count of OOM events.

    Example:
        oom_count = get_oom_killed_history("my-namespace", "my-workload", "my-container", "deployment", 60)
    """
    query = 'sum_over_time(kube_workload_container_resource_usage_memory_oom_killed{{namespace="{namespace}", workload="{workload}", workload_type="{workload_type}", container="{container}"}}[{lookback_minutes}m])'.format(
        namespace=namespace,
        workload=workload,
        workload_type=workload_type,
        container=container,
        lookback_minutes=lookback_minutes,
    )
    j = query_prometheus(query)

    if j["data"]["result"] == []:
        return 0

    if float(j["data"]["result"][0]["value"][1]) > 0:
        return round(float(j["data"]["result"][0]["value"][1]))

    return 0


@beartype
def is_nodejs_container(
    namespace: str, workload: str, container: str, workload_type: str = "deployment"
) -> bool:
    """
    Check if a container in a specific workload and namespace is a Node.js container.

    Args:
        namespace (str): The name of the Kubernetes namespace.
        workload (str): The name of the workload (e.g., deployment).
        container (str): The name of the container.
        workload_type (str, optional): The type of workload. Default is "deployment".

    Returns:
        bool: True if the container is a Node.js container, False otherwise.

    Example:
        is_nodejs = is_nodejs_container("my-namespace", "my-workload", "my-container", "deployment")
    """
    query = 'count(nodejs_version_info{{container="{container}"}} * on(namespace,pod) group_left(workload, workload_type) namespace_workload_pod:kube_pod_owner:relabel{{workload="{workload}", workload_type="{workload_type}", namespace="{namespace}"}}) by (namespace, workload, workload_type, container)'.format(
        namespace=namespace,
        workload=workload,
        workload_type=workload_type,
        container=container,
    )
    j = query_prometheus(query)

    if j["data"]["result"] == []:
        return False

    if float(j["data"]["result"][0]["value"][1]) > 0:
        return True

    return False


@beartype
def get_resources_from_deployment(deployment: V1Deployment) -> dict:
    """
    Get resource specifications (requests and limits) for containers in a deployment.

    Args:
        deployment (V1Deployment): The Kubernetes deployment object.

    Returns:
        dict: A dictionary containing resource specifications for each container.

    Example:
        deployment = get_deployment_by_name("my-namespace", "my-deployment")
        resources = get_resources_from_deployment(deployment)
    """
    res = {}
    for container in deployment.spec.template.spec.containers:
        res[container.name] = {}
        try:
            res[container.name]["requests"] = container.resources.requests
        except AttributeError:
            res[container.name]["requests"] = {}
        try:
            res[container.name]["limits"] = container.resources.limits
        except AttributeError:
            res[container.name]["limits"] = {}
    return res


@beartype
def calculate_lookback_minutes_from_deployment(deployment: V1Deployment) -> int:
    """
    Calculate the lookback minutes based on a deployment's creation and last update timestamps.

    Args:
        deployment (V1Deployment): The Kubernetes deployment object.

    Returns:
        int: The calculated lookback minutes.

    Raises:
        RuntimeError: If the deployment is too young or was modified too recently.

    Example:
        deployment = get_deployment_by_name("my-namespace", "my-deployment")
        lookback = calculate_lookback_minutes_from_deployment(deployment)
    """
    lookback_minutes = DEFAULT_LOOKBACK_MINUTES
    creation_minutes_ago = helpers.calculate_minutes_ago_from_timestamp(
        deployment.metadata.creation_timestamp
    )
    if creation_minutes_ago < CREATE_AGE_THRESHOLD:
        raise RuntimeError(
            f"The deployment is too young. It was created {creation_minutes_ago} minutes ago, which is below the minimum threshold of {CREATE_AGE_THRESHOLD} minutes."
        )

    lookback_minutes = creation_minutes_ago

    if "k8soptimizer.arvato-aws.io/last-update" in deployment.metadata.annotations:
        update_minutes_ago = helpers.calculate_minutes_ago_from_timestamp(
            deployment.metadata.creation_timestamp
        )
        if update_minutes_ago < UPDATE_AGE_THRESHOLD:
            raise RuntimeError(
                f"The deployment was modified too recently. It was updated {update_minutes_ago} minutes ago, which is below the minimum threshold of {UPDATE_AGE_THRESHOLD} minutes since creation."
            )
        lookback_minutes = min(
            lookback_minutes, (update_minutes_ago - OFFSET_LOOKBACK_MINUTES)
        )

    if lookback_minutes < MIN_LOOKBACK_MINUTES:
        raise RuntimeError(
            f"The specified lookback period ({lookback_minutes} minutes) is below the minimum required ({MIN_LOOKBACK_MINUTES} minutes). Please provide a longer lookback period to ensure sufficient historical data is available."
        )

    history_samples = get_number_of_samples_from_history(
        deployment.metadata.namespace,
        deployment.metadata.name,
        "deployment",
        lookback_minutes,
    )

    if history_samples < MIN_LOOKBACK_MINUTES:
        raise RuntimeError(
            f"The provided history samples ({history_samples}) are below the minimum required ({MIN_LOOKBACK_MINUTES}). Please ensure an adequate amount of historical data is available."
        )

    lookback_minutes = min(MAX_LOOKBACK_MINUTES, lookback_minutes, history_samples)

    return lookback_minutes


@beartype
def optimize_deployment(
    deployment: V1Deployment, container_pattern=CONTAINER_PATTERN, dry_run=True
) -> V1Deployment:
    """
    Optimize the resources (CPU and memory) for containers in a deployment.

    Args:
        deployment (V1Deployment): The Kubernetes deployment object to be optimized.
        dry_run (bool, optional): If True, the optimization changes will be simulated (dry-run mode).
                                 If False, the changes will be applied. Default is True.

    Returns:
        V1Deployment: The optimized Kubernetes deployment object.

    Example:
        deployment = get_deployment_by_name("my-namespace", "my-deployment")
        optimized_deployment = optimize_deployment(deployment, dry_run=True)
    """
    apis_api = client.AppsV1Api()
    namespace_name = deployment.metadata.namespace
    deployment_name = deployment.metadata.name
    _logger.info("Optimizing deployment: %s" % deployment_name)

    old_resources = get_resources_from_deployment(deployment)
    lookback_minutes = calculate_lookback_minutes_from_deployment(deployment)
    target_ratio = calculate_hpa_target_ratio(
        namespace_name, deployment_name, lookback_minutes
    )
    _logger.info("Target ratio cpu: %s" % target_ratio["cpu"])
    _logger.info("Target ratio memory: %s" % target_ratio["memory"])
    for i, container in enumerate(deployment.spec.template.spec.containers):
        container_name = container.name
        x = re.search(container_pattern, container_name)
        if x is None:
            _logger.debug(
                "Skipping container due to CONTAINER_PATTERN: %s" % container_name
            )
            continue

        container_new = optimize_container(
            namespace_name,
            deployment_name,
            container,
            "deployment",
            target_ratio["cpu"],
            target_ratio["memory"],
            lookback_minutes,
            deployment.spec.replicas,
        )
        deployment.spec.template.spec.containers[i] = container_new

    deployment.metadata.annotations[
        "k8soptimizer.{}/old-resources".format(__domain__)
    ] = json.dumps(old_resources)
    deployment.metadata.annotations[
        "k8soptimizer.{}/last-update".format(__domain__)
    ] = helpers.create_timestamp()

    # Apply the changes
    if dry_run is True:
        _logger.info("Updating (dry-run) deployment: %s" % deployment_name)
        apis_api.patch_namespaced_deployment(
            deployment_name,
            namespace_name,
            deployment,
            pretty=True,
            dry_run="All",
        )
    else:
        _logger.info("Updating deployment: %s" % deployment_name)
        apis_api.patch_namespaced_deployment(
            deployment_name, namespace_name, deployment, pretty=True
        )
    return deployment


@beartype
def optimize_container(
    namespace_name: str,
    workload: str,
    container: V1Container,
    workload_type: str = "deployment",
    target_ratio_cpu: float = 1,
    target_ratio_memory: float = 1,
    lookback_minutes: int = DEFAULT_LOOKBACK_MINUTES,
    current_replicas: int = 1,
) -> V1Container:
    """
    Optimize resources (CPU and memory) for a container.

    Args:
        namespace_name (str): The namespace of the container.
        workload (str): The name of the workload associated with the container.
        container (V1Container): The Kubernetes container object to be optimized.
        workload_type (str, optional): The type of workload (e.g., "deployment"). Default is "deployment".
        target_ratio_cpu (float, optional): The target ratio for CPU optimization. Default is 1.
        target_ratio_memory (float, optional): The target ratio for memory optimization. Default is 1.
        lookback_minutes (int, optional): The lookback minutes for historical data. Default is DEFAULT_LOOKBACK_MINUTES.
        current_replicas (int, optional): The current number of replicas. Default is 1.

    Returns:
        V1Container: The optimized Kubernetes container object.

    Example:
        namespace = "my-namespace"
        workload = "my-workload"
        container = get_container_by_name(namespace, workload, "my-container")
        optimized_container = optimize_container(namespace, workload, container, target_ratio_cpu=0.8)
    """
    container_name = container.name

    _logger.info("Processing container: %s" % container_name)

    old_cpu = get_cpu_requests_from_container(container)
    new_cpu = optimize_container_cpu_requests(
        namespace_name,
        workload,
        container,
        workload_type,
        target_ratio_cpu,
        lookback_minutes,
    )
    old_memory = get_memory_requests_from_container(container)
    new_memory = optimize_container_memory_requests(
        namespace_name,
        workload,
        container,
        workload_type,
        target_ratio_memory,
        lookback_minutes,
    )
    new_memory_limit = optimize_container_memory_limits(
        namespace_name, workload, container, workload_type, new_memory
    )

    stats["old_cpu_sum"] += old_cpu * current_replicas
    stats["new_cpu_sum"] += new_cpu * current_replicas
    stats["old_memory_sum"] += old_memory * current_replicas
    stats["new_memory_sum"] += new_memory * current_replicas

    container.resources.requests["cpu"] = str(round(new_cpu * 1000)) + "m"
    if "cpu" in container.resources.limits:
        del container.resources.limits["cpu"]
    container.resources.requests["memory"] = str(round(new_memory / 1024 / 1024)) + "Mi"
    container.resources.limits["memory"] = (
        str(round(new_memory_limit / 1024 / 1024)) + "Mi"
    )

    return container


@beartype
def get_cpu_requests_from_container(container: V1Container) -> float:
    """
    Get the CPU requests from a Kubernetes container.

    Args:
        container (V1Container): The Kubernetes container object.

    Returns:
        float: The CPU requests in cores.

    Example:
        container = V1Container(name="my-container", resources=V1ResourceRequirements(requests={"cpu": "100m"}))
        cpu_requests = get_cpu_requests_from_container(container)
    """
    try:
        old_cpu = helpers.convert_cpu_request_to_cores(
            container.resources.requests["cpu"]
        )
    except (KeyError, AttributeError):
        old_cpu = 0.001
    return float(old_cpu)


@beartype
def get_memory_requests_from_container(container: V1Container) -> int:
    """
    Get the memory requests from a Kubernetes container.

    Args:
        container (V1Container): The Kubernetes container object.

    Returns:
        int: The memory requests in bytes.

    Example:
        container = V1Container(name="my-container", resources=V1ResourceRequirements(requests={"memory": "2Gi"}))
        memory_requests = get_memory_requests_from_container(container)
    """
    try:
        old_memory = helpers.convert_memory_request_to_bytes(
            container.resources.requests["memory"]
        )
    except (KeyError, AttributeError):
        old_memory = 1024**2 * 1
    return int(old_memory)


@beartype
def get_memory_limits_from_container(container: V1Container) -> int:
    """
    Get the memory limits from a Kubernetes container.

    Args:
        container (V1Container): The Kubernetes container object.

    Returns:
        int: The memory limits in bytes.

    Example:
        container = V1Container(name="my-container", resources=V1ResourceRequirements(limits={"memory": "4Gi"}))
        memory_limits = get_memory_limits_from_container(container)
    """
    try:
        old_memory = helpers.convert_memory_request_to_bytes(
            container.resources.limits["memory"]
        )
    except (KeyError, AttributeError):
        old_memory = 1024**2 * 1
    return int(old_memory)


@beartype
def optimize_container_cpu_requests(
    namespace_name: str,
    workload: str,
    container: V1Container,
    workload_type: str = "deployment",
    target_ratio: float = 1,
    lookback_minutes: int = DEFAULT_LOOKBACK_MINUTES,
) -> float:
    """
    Optimize CPU requests for a Kubernetes container.

    Args:
        namespace_name (str): The namespace of the workload.
        workload (str): The name of the workload.
        container (V1Container): The Kubernetes container object.
        workload_type (str, optional): The type of workload. Defaults to "deployment".
        target_ratio (float, optional): The target ratio for CPU optimization. Defaults to 1.
        lookback_minutes (int, optional): The number of minutes to look back for resource usage data. Defaults to DEFAULT_LOOKBACK_MINUTES.

    Returns:
        float: The new CPU request in cores.

    Example:
        namespace_name = "my-namespace"
        workload = "my-workload"
        container = V1Container(name="my-container", resources=V1ResourceRequirements(requests={"cpu": "100m"}))
        new_cpu = optimize_container_cpu_requests(namespace_name, workload, container)
    """
    container_name = container.name

    try:
        _logger.debug(container.resources.requests["cpu"])
        old_cpu = helpers.convert_cpu_request_to_cores(
            container.resources.requests["cpu"]
        )
    except (KeyError, AttributeError):
        _logger.info("Could not read old CPU requests aassuming it is 0.001")
        old_cpu = 0.001

    new_cpu = calculate_cpu_requests(
        namespace_name,
        workload,
        workload_type,
        container_name,
        target_ratio,
        lookback_minutes,
    )

    diff_cpu = round(((new_cpu / old_cpu) - 1) * 100)

    if abs(diff_cpu) < CHANGE_THRESHOLD * 100:
        _logger.info("CPU requests change is too small: {}%".format(diff_cpu))
        new_cpu = old_cpu
    else:
        _logger.info(
            "CPU requests change: {} -> {} ({}%)".format(
                str(round(old_cpu * 1000)) + "m",
                str(round(new_cpu * 1000)) + "m",
                diff_cpu,
            )
        )

    return float(new_cpu)


@beartype
def optimize_container_memory_requests(
    namespace_name: str,
    workload: str,
    container: V1Container,
    workload_type: str = "deployment",
    target_ratio: float = 1,
    lookback_minutes: int = DEFAULT_LOOKBACK_MINUTES,
) -> int:
    """
    Optimize memory requests for a Kubernetes container.

    Args:
        namespace_name (str): The namespace of the workload.
        workload (str): The name of the workload.
        container (V1Container): The Kubernetes container object.
        workload_type (str, optional): The type of workload. Defaults to "deployment".
        target_ratio (float, optional): The target ratio for memory optimization. Defaults to 1.
        lookback_minutes (int, optional): The number of minutes to look back for resource usage data. Defaults to DEFAULT_LOOKBACK_MINUTES.

    Returns:
        int: The new memory request in bytes.

    Example:
        namespace_name = "my-namespace"
        workload = "my-workload"
        container = V1Container(name="my-container", resources=V1ResourceRequirements(requests={"memory": "1Gi"}))
        new_memory = optimize_container_memory_requests(namespace_name, workload, container)
    """
    container_name = container.name

    try:
        _logger.debug(container.resources.requests["memory"])
        old_memory = helpers.convert_memory_request_to_bytes(
            container.resources.requests["memory"]
        )
    except (KeyError, AttributeError):
        _logger.info("Could not read old meory requests aassuming it is 1")
        old_memory = 1

    new_memory = calculate_memory_requests(
        namespace_name,
        workload,
        workload_type,
        container_name,
        target_ratio,
        lookback_minutes,
    )
    diff_memory = round(((new_memory / old_memory) - 1) * 100)

    if abs(diff_memory) < CHANGE_THRESHOLD * 100:
        _logger.info("Memory request change is too small: {}%".format(diff_memory))
        new_memory = old_memory
    else:
        _logger.info(
            "Memory requests change: {} -> {} ({}%)".format(
                str(round(old_memory / 1024 / 1024)) + "Mi",
                str(round(new_memory / 1024 / 1024)) + "Mi",
                diff_memory,
            )
        )
    return int(new_memory)


@beartype
def optimize_container_memory_limits(
    namespace_name: str,
    workload: str,
    container: V1Container,
    workload_type: str = "deployment",
    new_memory: int = MIN_MEMORY_REQUEST,
) -> int:
    """
    Optimize memory limits for a Kubernetes container.

    Args:
        namespace_name (str): The namespace of the workload.
        workload (str): The name of the workload.
        container (V1Container): The Kubernetes container object.
        workload_type (str, optional): The type of workload. Defaults to "deployment".
        new_memory (int, optional): The new memory request in bytes. Defaults to MIN_MEMORY_REQUEST.

    Returns:
        int: The new memory limit in bytes.

    Example:
        namespace_name = "my-namespace"
        workload = "my-workload"
        container = V1Container(name="my-container", resources=V1ResourceRequirements(limits={"memory": "2Gi"}))
        new_memory_limit = optimize_container_memory_limits(namespace_name, workload, container)
    """
    container_name = container.name

    try:
        old_memory_limit = helpers.convert_memory_request_to_bytes(
            container.resources.limits["memory"]
        )
    except (KeyError, AttributeError):
        _logger.info("Could not read old meory limits aassuming it is 1")
        old_memory_limit = 1

    new_memory_limit = calculate_memory_limits(
        namespace_name, workload, workload_type, container_name, new_memory
    )
    diff_memory_limit = round(((new_memory_limit / old_memory_limit) - 1) * 100)

    if abs(diff_memory_limit) < CHANGE_THRESHOLD * 100:
        _logger.info("Memory limit change is too small: {}%".format(diff_memory_limit))
        new_memory_limit = old_memory_limit
    else:
        _logger.info(
            "Memory limits change: {} -> {} ({}%)".format(
                str(round(old_memory_limit / 1024 / 1024)) + "Mi",
                str(round(new_memory_limit / 1024 / 1024)) + "Mi",
                diff_memory_limit,
            )
        )

    return int(new_memory_limit)


# ---- CLI ----
# The functions defined in this section are wrappers around the main Python
# API allowing them to be called directly from the terminal as a CLI
# executable/script.


def parse_args(args):
    """Parse command line parameters

    Args:
      args (List[str]): command line parameters as list of strings
          (for example  ``["--help"]``).

    Returns:
      :obj:`argparse.Namespace`: command line parameters namespace
    """
    parser = argparse.ArgumentParser(description="k8soptimizer")
    parser.add_argument(
        "--version",
        action="version",
        version=f"k8soptimizer {__version__}",
    )
    # parser.add_argument(dest="n", help="n-th Fibonacci number", type=int, metavar="INT")
    parser.add_argument(
        "-v",
        "--verbose",
        dest="loglevel",
        help="set loglevel to INFO",
        action="store_const",
        const=logging.INFO,
    )
    parser.add_argument(
        "-vv",
        "--very-verbose",
        dest="loglevel",
        help="set loglevel to DEBUG",
        action="store_const",
        const=logging.DEBUG,
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        default=DRY_RUN_MODE,
        help="Perform a dry run without making any actual changes.",
        dest="dry_run",
    )

    group_ns = parser.add_mutually_exclusive_group()
    group_ns.add_argument(
        "-n",
        "--namespace",
        action="store",
        help="Set namespace",
        dest="namespace",
        type=helpers.valid_k8s_name_arg,
    )
    group_ns.add_argument(
        "--namespace-pattern",
        action="store",
        default=NAMESPACE_PATTERN,
        help="Set namespace pattern (regex)",
        dest="namespace_pattern",
        type=helpers.valid_regex_arg,
    )

    group_ds = parser.add_mutually_exclusive_group()
    group_ds.add_argument(
        "-d",
        "--deployment",
        action="store",
        help="Set deployment",
        dest="deployment",
        type=helpers.valid_k8s_name_arg,
    )
    parser.add_argument(
        "--deployment-pattern",
        action="store",
        default=DEPLOYMENT_PATTERN,
        help="Set deployment pattern (regex)",
        dest="deplopyment_pattern",
        type=helpers.valid_regex_arg,
    )

    group_cs = parser.add_mutually_exclusive_group()
    group_cs.add_argument(
        "-c",
        "--container",
        action="store",
        help="Set container",
        dest="container",
        type=helpers.is_valid_k8s_name,
    )
    group_cs.add_argument(
        "--container-pattern",
        action="store",
        default=DEPLOYMENT_PATTERN,
        help="Set container pattern (regex)",
        dest="container_pattern",
        type=helpers.valid_regex_arg,
    )

    return parser.parse_args(args)


def setup_logging(loglevel):
    """Setup basic logging

    Args:
        loglevel (int): minimum loglevel for emitting messages
    """
    logformat = "[%(asctime)s] %(levelname)s:%(name)s:%(message)s"
    logging.basicConfig(
        level=loglevel, stream=sys.stdout, format=logformat, datefmt="%Y-%m-%d %H:%M:%S"
    )


def main(args):
    """Wrapper allowing :func:`fib` to be called with string arguments in a CLI fashion

    Instead of returning the value from :func:`fib`, it prints the result to the
    ``stdout`` in a nicely formatted message.

    Args:
        args (List[str]): command line parameters as list of strings
            (for example  ``["--verbose", "42"]``).
    """
    args = parse_args(args)
    setup_logging(args.loglevel)
    _logger.info("Starting k8soptimizer...")

    verify_kubernetes_connection()
    verify_prometheus_connection()

    namespace_pattern = args.namespace_pattern
    if args.namespace is not None:
        namespace_pattern = "^{}$".format(args.namespace)
    deplopyment_pattern = args.deplopyment_pattern
    if args.deployment is not None:
        deplopyment_pattern = "^{}$".format(args.deployment)
    container_pattern = args.container_pattern
    if args.container is not None:
        container_pattern = "^{}$".format(args.container)
    _logger.info("Using namespace_pattern: {}".format(namespace_pattern))
    _logger.info("Using deplopyment_pattern: {}".format(deplopyment_pattern))
    _logger.info("Using container_pattern: {}".format(container_pattern))

    for namespace in get_namespaces(namespace_pattern).items:
        for deployment in get_deployments(
            namespace.metadata.name, deplopyment_pattern
        ).items:
            try:
                optimize_deployment(deployment, container_pattern, args.dry_run)
            except Exception as e:
                _logger.exception(
                    "An error occurred while optimizing the deployment: %s", str(e)
                )

    if stats["old_cpu_sum"] > 0:
        diff_cpu_sum = round(((stats["new_cpu_sum"] / stats["old_cpu_sum"]) - 1) * 100)
        diff_memory_sum = round(
            ((stats["new_memory_sum"] / stats["old_memory_sum"]) - 1) * 100
        )

        _logger.info(
            "Summary cpu requests change: {} -> {} ({}%)".format(
                str(round(stats["old_cpu_sum"] * 1000)) + "m",
                str(round(stats["new_cpu_sum"] * 1000)) + "m",
                diff_cpu_sum,
            )
        )

        _logger.info(
            "Summary memory requests change: {} -> {} ({}%)".format(
                str(round(stats["old_memory_sum"] / 1024 / 1024)) + "Mi",
                str(round(stats["new_memory_sum"] / 1024 / 1024)) + "Mi",
                diff_memory_sum,
            )
        )

    _logger.info("Finished k8soptimizer")


def run():
    """Calls :func:`main` passing the CLI arguments extracted from :obj:`sys.argv`

    This function can be used as entry point to create console scripts with setuptools.
    """
    main(sys.argv[1:])


if __name__ == "__main__":
    # ^  This is a guard statement that will prevent the following code from
    #    being executed in the case someone imports this file instead of
    #    executing it as a script.
    #    https://docs.python.org/3/library/__main__.html

    # After installing your project with pip, users can also run your Python
    # modules as scripts via the ``-m`` flag, as defined in PEP 338::
    #
    #     python -m k8soptimizer.skeleton 42
    #
    run()
