import json
import unittest
from datetime import datetime, timedelta, timezone

# Standard library imports...
from unittest.mock import patch

import pytest
from kubernetes.client.models import (
    V1Container,
    V1Deployment,
    V1DeploymentList,
    V1DeploymentSpec,
    V1LabelSelector,
    V1Namespace,
    V1NamespaceList,
    V1ObjectMeta,
    V1PodSpec,
    V1PodTemplateSpec,
    V1ResourceRequirements,
    V2CrossVersionObjectReference,
    V2HorizontalPodAutoscaler,
    V2HorizontalPodAutoscalerList,
    V2HorizontalPodAutoscalerSpec,
    V2MetricSpec,
    V2MetricTarget,
    V2ResourceMetricSource,
)

import k8soptimizer.main as main

__author__ = "Philipp Hellmich"
__copyright__ = "Arvato Systems GmbH"
__license__ = "MIT"


@patch("requests.get")  # Mock the requests.get function
def test_query_prometheus(mock_requests_get):
    # Define your test data and expected response
    expected_result = {"data": {"result": [{"value": [0, 42]}]}}

    # Mock the response from requests.get
    mock_response = unittest.mock.Mock()
    mock_response.text = json.dumps(expected_result)
    mock_requests_get.return_value = mock_response

    # Call the function under test
    result = main.query_prometheus("node_load1")

    # Verify that the function behaves as expected
    assert result == expected_result  # Check if the result is as expected


@patch("requests.get")  # Mock the requests.get function
def test_verify_prometheus_connection(mock_requests_get):
    # Define your test data and expected response
    expected_result = {"status": "success"}

    # Mock the response from requests.get
    mock_response = unittest.mock.Mock()
    mock_response.text = json.dumps(expected_result)
    mock_requests_get.return_value = mock_response

    # Call the function under test
    result = main.verify_prometheus_connection()

    # Verify that the function behaves as expected
    assert result is True  # Check if the result is as expected


@patch("k8soptimizer.main.query_prometheus")
def test_get_max_pods_per_deployment_history(mock_func1):
    # Define your test data and expected response
    namespace_name = "test_namespace"
    deployment_name = "test_deployment"

    mock_func1.return_value = {"data": {"result": [{"value": [0, 42]}]}}

    # Call the function under test
    result = main.get_max_pods_per_deployment_history(
        namespace_name,
        deployment_name,
        lookback_minutes=3600 * 7 * 24,
        quantile_over_time=0.95,
    )

    # Verify that the function behaves as expected
    assert (
        result == mock_func1.return_value["data"]["result"][0]["value"][1]
    )  # Check if the result is as expected

    mock_func1.return_value = {"data": {"result": []}}

    with pytest.raises(RuntimeError) as exc_info:
        main.get_max_pods_per_deployment_history(
            namespace_name,
            deployment_name,
            lookback_minutes=3600 * 24 * 7,
            quantile_over_time=0.95,
        )

    # Check the exception message or other attributes if needed
    assert "No data found" in str(exc_info.value)


@patch("k8soptimizer.main.query_prometheus")
def test_get_cpu_cores_usage_history(mock_func1):
    # Define your test data and expected response
    namespace_name = "test_namespace"
    deployment_name = "test_deployment"

    mock_func1.return_value = {"data": {"result": [{"value": [0, 8]}]}}

    # Call the function under test
    result = main.get_cpu_cores_usage_history(
        namespace_name,
        deployment_name,
        "nginx",
        lookback_minutes=3600 * 7 * 24,
        quantile_over_time=0.95,
    )

    # Verify that the function behaves as expected
    assert (
        result == mock_func1.return_value["data"]["result"][0]["value"][1]
    )  # Check if the result is as expected

    mock_func1.return_value = {"data": {"result": []}}

    with pytest.raises(RuntimeError) as exc_info:
        main.get_cpu_cores_usage_history(
            namespace_name,
            deployment_name,
            "nginx",
            lookback_minutes=3600 * 24 * 7,
            quantile_over_time=0.95,
        )

    # Check the exception message or other attributes if needed
    assert "No data found" in str(exc_info.value)


@patch("k8soptimizer.main.query_prometheus")
def test_get_memory_bytes_usage_history(mock_func1):
    # Define your test data and expected response
    namespace_name = "test_namespace"
    deployment_name = "test_deployment"

    mock_func1.return_value = {"data": {"result": [{"value": [0, 1024 * 8]}]}}

    # Call the function under test
    result = main.get_memory_bytes_usage_history(
        namespace_name,
        deployment_name,
        "nginx",
        lookback_minutes=3600 * 7 * 24,
        quantile_over_time=0.95,
    )

    # Verify that the function behaves as expected
    assert (
        result == mock_func1.return_value["data"]["result"][0]["value"][1]
    )  # Check if the result is as expected

    mock_func1.return_value = {"data": {"result": []}}

    with pytest.raises(RuntimeError) as exc_info:
        main.get_memory_bytes_usage_history(
            namespace_name,
            deployment_name,
            "nginx",
            lookback_minutes=3600 * 24 * 7,
            quantile_over_time=0.95,
        )

    # Check the exception message or other attributes if needed
    assert "No data found" in str(exc_info.value)


@patch("k8soptimizer.main.query_prometheus")
def test_discover_container_runtime(mock_func1):
    # Define your test data and expected response
    namespace_name = "test_namespace"
    deployment_name = "test_deployment"

    mock_func1.return_value = {"data": {"result": [{"value": [0, 1]}]}}

    # Call the function under test
    result = main.discover_container_runtime(namespace_name, deployment_name, "nodejs")

    # Verify that the function behaves as expected
    assert result == "nodejs"  # Check if the result is as expected

    mock_func1.return_value = {"data": {"result": [{"value": [0, 0]}]}}

    # Call the function under test
    result = main.discover_container_runtime(namespace_name, deployment_name, "nginx")

    # Verify that the function behaves as expected
    assert result is None  # Check if the result is as expected


@patch(
    "k8soptimizer.main.client.CoreV1Api.list_namespace"
)  # Mock the requests.get function
def test_get_namespaces(mock_requests_get):
    # Define a list of V1Namespace objects
    namespace1 = V1Namespace(metadata=V1ObjectMeta(name="namespace1"))
    namespace2 = V1Namespace(metadata=V1ObjectMeta(name="namespace2"))
    namespace_list = V1NamespaceList(items=[namespace1, namespace2])

    mock_requests_get.return_value = namespace_list

    # Call the function under test
    result = main.get_namespaces(".*")

    # Verify that the function behaves as expected
    assert len(result.items) == 2  # Check if the result is as expected

    # Define a list of V1Namespace objects
    namespace_list = V1NamespaceList(items=[namespace1])

    mock_requests_get.return_value = namespace_list

    # Call the function under test
    result = main.get_namespaces("namespace1")

    assert len(result.items) == 1  # Check if the result is as expected
    assert (
        result.items[0].metadata.name == "namespace1"
    )  # Check if the result is as expected

    # Call the function under test
    result = main.get_namespaces("namespaceX")

    assert len(result.items) == 0  # Check if the result is as expected


@patch(
    "k8soptimizer.main.client.AppsV1Api.list_namespaced_deployment"
)  # Mock the requests.get function
def test_get_deployments(mock_requests_get):
    # Define a list of V1Namespace objects
    deployment1 = V1Deployment(
        metadata=V1ObjectMeta(
            name="deployment1",
            namespace="default",
        ),
        spec=V1DeploymentSpec(
            replicas=1,
            selector=V1LabelSelector(match_labels={"app": "nginx"}),
            template=V1PodTemplateSpec(
                spec=V1PodSpec(
                    containers=[
                        V1Container(
                            name="nginx",
                            resources=V1ResourceRequirements(
                                requests={"cpu": "1"}, limits={"cpu": "1"}
                            ),
                        )
                    ]
                )
            ),
        ),
    )
    deployment2 = V1Deployment(
        metadata=V1ObjectMeta(
            name="deployment2",
            namespace="default",
        ),
        spec=V1DeploymentSpec(
            replicas=2,
            selector=V1LabelSelector(match_labels={"app": "nginx"}),
            template=V1PodTemplateSpec(
                spec=V1PodSpec(
                    containers=[
                        V1Container(
                            name="nginx",
                            resources=V1ResourceRequirements(limits={"cpu": "2"}),
                        )
                    ]
                )
            ),
        ),
    )
    deployment3 = V1Deployment(
        metadata=V1ObjectMeta(
            name="deployment3",
        ),
        spec=V1DeploymentSpec(
            replicas=0,
            selector=V1LabelSelector(match_labels={"app": "nginx"}),
            template=V1PodTemplateSpec(
                spec=V1PodSpec(
                    containers=[
                        V1Container(
                            name="nginx",
                            resources=V1ResourceRequirements(limits={"cpu": "1"}),
                        )
                    ]
                )
            ),
        ),
    )
    deployment_list = V1DeploymentList(items=[deployment1, deployment2, deployment3])

    mock_requests_get.return_value = deployment_list

    # Call the function under test
    result = main.get_deployments("default", ".*")

    # Verify that the function behaves as expected
    assert len(result.items) == 2  # Check if the result is as expected

    # Define a list of V1Namespace objects
    deployment_list = V1DeploymentList(items=[deployment1, deployment2])

    mock_requests_get.return_value = deployment_list

    # Call the function under test
    result = main.get_deployments("default", "^deployment1$")

    assert len(result.items) == 1  # Check if the result is as expected
    assert (
        result.items[0].metadata.name == "deployment1"
    )  # Check if the result is as expected

    # Call the function under test
    result = main.get_deployments("default", "deploymentX")

    assert len(result.items) == 0  # Check if the result is as expected


@patch(
    "k8soptimizer.main.client.AutoscalingV2Api.list_namespaced_horizontal_pod_autoscaler"
)  # Mock the requests.get function
def test_get_hpa_for_deployment(mock_requests_get):
    hpa1 = V2HorizontalPodAutoscaler(
        metadata=V1ObjectMeta(name="deployment1"),
        spec=V2HorizontalPodAutoscalerSpec(
            max_replicas=10,
            min_replicas=1,
            metrics=[
                V2MetricSpec(
                    type="Resource",
                    resource=V2ResourceMetricSource(
                        name="cpu",
                        target=V2MetricTarget(
                            average_utilization=80, type="Utilization"
                        ),
                    ),
                )
            ],
            scale_target_ref=V2CrossVersionObjectReference(
                kind="Deployment", name="deployment1"
            ),
        ),
    )

    hpa2 = V2HorizontalPodAutoscaler(
        metadata=V1ObjectMeta(name="deployment2"),
        spec=V2HorizontalPodAutoscalerSpec(
            max_replicas=10,
            min_replicas=1,
            metrics=[
                V2MetricSpec(
                    type="Resource",
                    resource=V2ResourceMetricSource(
                        name="cpu",
                        target=V2MetricTarget(
                            average_utilization=80, type="Utilization"
                        ),
                    ),
                )
            ],
            scale_target_ref=V2CrossVersionObjectReference(
                kind="Deployment", name="deployment2"
            ),
        ),
    )
    hpa_list = V2HorizontalPodAutoscalerList(items=[hpa1, hpa2])

    mock_requests_get.return_value = hpa_list

    # Call the function under test
    result = main.get_hpa_for_deployment("default", "deployment1")

    assert result is not None

    assert result.metadata.name == "deployment1"


test_data_cpu = [
    # Test case 0: Normal case
    {
        "input_params": {
            "cpu_history": main.MIN_CPU_REQUEST + 1,
            "target_replicas": 1,
            "runtime": None,
        },
        "expected_output": main.MIN_CPU_REQUEST + 1,
    },
    # Test case 1: Below min cpu
    {
        "input_params": {
            "cpu_history": 0.000001,
            "target_replicas": 1,
            "runtime": None,
        },
        "expected_output": main.MIN_CPU_REQUEST,
    },
    # Test case 2: Below min cpu
    {
        "input_params": {
            "cpu_history": 1,
            "target_replicas": 9999999999,
            "runtime": None,
        },
        "expected_output": main.MIN_CPU_REQUEST,
    },
    # Test case 3: Higher max cpu
    {
        "input_params": {
            "cpu_history": 9999999999,
            "target_replicas": 2,
            "runtime": None,
        },
        "expected_output": main.MAX_CPU_REQUEST,
    },
    # Test case 4: Higher max cpu
    {
        "input_params": {
            "cpu_history": main.MAX_CPU_REQUEST + 1,
            "target_replicas": 1,
            "runtime": None,
        },
        "expected_output": main.MAX_CPU_REQUEST,
    },
    # Test case 5: nodejs
    {
        "input_params": {
            "cpu_history": 10,
            "target_replicas": 2,
            "runtime": "nodejs",
        },
        "expected_output": main.MAX_CPU_REQUEST_NODEJS,
    },
]


@pytest.mark.parametrize("test_case", test_data_cpu)
@patch("k8soptimizer.main.discover_container_runtime")
@patch("k8soptimizer.main.get_cpu_cores_usage_history")
def test_calculate_cpu_requests(mock_func1, mock_func2, test_case):
    namespace_name = "test_namespace"
    deployment_name = "test_deployment"
    input_params = test_case["input_params"]
    expected_output = test_case["expected_output"]

    mock_func1.return_value = input_params["cpu_history"]
    mock_func2.return_value = None

    input_params = test_case["input_params"]
    expected_output = test_case["expected_output"]

    if "runtime" in input_params:
        mock_func2.return_value = input_params["runtime"]

    # Call the function under test
    result = main.calculate_cpu_requests(
        namespace_name,
        deployment_name,
        "development",
        "nginx",
        input_params["target_replicas"],
        main.DEFAULT_LOOKBACK_MINUTES,
    )

    assert result == pytest.approx(expected_output, rel=1e-2)


test_data_memory = [
    # Test case 0: Normal case
    {
        "input_params": {
            "memory_history": main.MIN_MEMORY_REQUEST + 1024,
            "memory_ratio": 1.0,
            "runtime": None,
        },
        "expected_output": main.MIN_MEMORY_REQUEST + 1024,
    },
    # Test case 1: Below min memory
    {
        "input_params": {
            "memory_history": 0.000001,
            "memory_ratio": 1.0,
            "runtime": None,
        },
        "expected_output": main.MIN_MEMORY_REQUEST,
    },
    # Test case 2: Below min memory
    {
        "input_params": {
            "memory_history": 1,
            "memory_ratio": 000000.1,
            "runtime": None,
        },
        "expected_output": main.MIN_MEMORY_REQUEST,
    },
    # Test case 3: Higher max memory
    {
        "input_params": {
            "memory_history": 999999999999999,
            "memory_ratio": 1.0,
            "runtime": None,
        },
        "expected_output": main.MAX_MEMORY_REQUEST,
    },
    # Test case 4: Higher max memory
    {
        "input_params": {
            "memory_history": 1,
            "memory_ratio": 999999999999999.0,
            "runtime": None,
        },
        "expected_output": main.MAX_MEMORY_REQUEST,
    },
    # Test case 5: nodejs
    {
        "input_params": {
            "memory_history": 10,
            "memory_ratio": 999999999999999.0,
            "runtime": "nodejs",
        },
        "expected_output": main.MAX_MEMORY_REQUEST,
    },
    # Test case 6: OOM killed
    {
        "input_params": {
            "memory_history": main.MIN_MEMORY_REQUEST + 1024,
            "memory_ratio": 1.0,
            "runtime": None,
            "oom_killed": 11,
        },
        "expected_output": (main.MIN_MEMORY_REQUEST + 1024) * 2,
    },
]


@pytest.mark.parametrize("test_case", test_data_memory)
@patch("k8soptimizer.main.get_oom_killed_history")
@patch("k8soptimizer.main.discover_container_runtime")
@patch("k8soptimizer.main.get_memory_bytes_usage_history")
def test_calculate_memory_requests(mock_func1, mock_func2, mock_func3, test_case):
    namespace_name = "test_namespace"
    deployment_name = "test_deployment"
    input_params = test_case["input_params"]
    expected_output = test_case["expected_output"]

    mock_func1.return_value = input_params["memory_history"]
    mock_func2.return_value = None
    mock_func3.return_value = 0

    if "runtime" in input_params:
        mock_func2.return_value = input_params["runtime"]
    if "oom_killed" in input_params:
        mock_func3.return_value = input_params["oom_killed"]

    # Call the function under test
    result = main.calculate_memory_requests(
        namespace_name,
        deployment_name,
        "development",
        "nginx",
        input_params["memory_ratio"],
        main.DEFAULT_LOOKBACK_MINUTES,
    )

    assert result == pytest.approx(expected_output, rel=1e-2)


test_data_optimize_container = [
    # Test case 0: Normal case with cpu and memory limits
    {
        "input_params": {
            "old_requests": {"cpu": "6", "memory": "1G"},
            "old_limits": {"cpu": "1", "memory": "10G"},
            "new_requests": {"cpu": 3, "memory": 1024**3 * 2},
            "new_limits": {"cpu": 3, "memory": 1024**3 * 4},
        },
        "expected_output": {
            "requests": {"cpu": "3000m", "memory": "2048Mi"},
            "limits": {"memory": "4096Mi"},
        },
    },
    # Test case 1: Normal case with no limits
    {
        "input_params": {
            "old_requests": {"cpu": "6", "memory": "1G"},
            "old_limits": {},
            "new_requests": {"cpu": 3, "memory": 1024**3 * 2},
            "new_limits": {"cpu": 3, "memory": 1024**3 * 4},
        },
        "expected_output": {
            "requests": {"cpu": "3000m", "memory": "2048Mi"},
            "limits": {"memory": "4096Mi"},
        },
    },
    # Test case 2: Normal case with no limits
    {
        "input_params": {
            "old_requests": {"cpu": "6", "memory": "1G"},
            "old_limits": {},
            "new_requests": {"cpu": 1.0, "memory": 1024**3 * 2},
            "new_limits": {"memory": 1024**3 * 4},
        },
        "expected_output": {
            "requests": {"cpu": "1000m", "memory": "2048Mi"},
            "limits": {"memory": "4096Mi"},
        },
    },
]


@pytest.mark.parametrize("test_case", test_data_optimize_container)
@patch("k8soptimizer.main.calculate_memory_limits")
@patch("k8soptimizer.main.calculate_memory_requests")
@patch("k8soptimizer.main.calculate_cpu_requests")
def test_optimize_container(mock_func1, mock_func2, mock_func3, test_case):
    expected_output = test_case["expected_output"]

    mock_func1.return_value = test_case["input_params"]["new_requests"]["cpu"]
    mock_func2.return_value = test_case["input_params"]["new_requests"]["memory"]
    mock_func3.return_value = test_case["input_params"]["new_limits"]["memory"]

    container = V1Container(
        name="nginx",
        resources=V1ResourceRequirements(
            requests=test_case["input_params"]["old_requests"],
            limits=test_case["input_params"]["old_limits"],
        ),
    )

    container, changed = main.optimize_container(
        "default",
        "deployment1",
        container,
        "deployment",
        1.0,
        1.0,
        main.DEFAULT_LOOKBACK_MINUTES,
    )

    assert container.resources.requests == expected_output["requests"]
    assert container.resources.limits == expected_output["limits"]
    assert changed


def test_get_resources_from_deployment():
    # Define a list of V1Namespace objects
    deployment1 = V1Deployment(
        metadata=V1ObjectMeta(
            name="deployment1",
        ),
        spec=V1DeploymentSpec(
            replicas=1,
            selector=V1LabelSelector(match_labels={"app": "nginx"}),
            template=V1PodTemplateSpec(
                spec=V1PodSpec(
                    containers=[
                        V1Container(
                            name="nginx",
                            resources=V1ResourceRequirements(
                                requests={"cpu": "1"}, limits={"cpu": "1"}
                            ),
                        ),
                        V1Container(
                            name="php",
                            resources=V1ResourceRequirements(
                                requests={"cpu": "8", "memory": "6Gi"}, limits={}
                            ),
                        ),
                        V1Container(name="php-monitor"),
                    ]
                )
            ),
        ),
    )

    expected_result = {
        "nginx": {
            "requests": deployment1.spec.template.spec.containers[0].resources.requests,
            "limits": deployment1.spec.template.spec.containers[0].resources.limits,
        },
        "php": {
            "requests": deployment1.spec.template.spec.containers[1].resources.requests,
            "limits": {},
        },
        "php-monitor": {"requests": {}, "limits": {}},
    }
    result = main.get_resources_from_deployment(deployment1)

    for key, value in expected_result.items():
        assert result[key] == value

    # assert result == expected_result


@patch("k8soptimizer.main.client.AppsV1Api.patch_namespaced_deployment")
@patch("k8soptimizer.main.calculate_lookback_minutes_from_deployment")
@patch("k8soptimizer.main.calculate_hpa_target_ratio")
@patch("k8soptimizer.main.optimize_container")
def test_optimize_deployment(mock_func1, mock_func2, mock_func3, mock_func4):
    deployment1_input = V1Deployment(
        metadata=V1ObjectMeta(
            name="deployment1",
            namespace="default",
            creation_timestamp=datetime.now(timezone.utc) - timedelta(days=1),
            annotations={},
        ),
        spec=V1DeploymentSpec(
            replicas=1,
            selector=V1LabelSelector(match_labels={"app": "nginx"}),
            template=V1PodTemplateSpec(
                spec=V1PodSpec(
                    containers=[
                        V1Container(
                            name="nginx",
                            resources=V1ResourceRequirements(
                                requests={"cpu": "1"}, limits={"cpu": "1"}
                            ),
                        ),
                        V1Container(
                            name="php",
                            resources=V1ResourceRequirements(
                                requests={"cpu": "2", "memory": "4Gi"}, limits={}
                            ),
                        ),
                        V1Container(name="php-monitor"),
                    ]
                )
            ),
        ),
    )

    deployment1_output = V1Deployment(
        metadata=V1ObjectMeta(
            name="deployment1",
            namespace="default",
            creation_timestamp=datetime.now(timezone.utc) - timedelta(days=1),
            annotations={},
        ),
        spec=V1DeploymentSpec(
            replicas=1,
            selector=V1LabelSelector(match_labels={"app": "nginx"}),
            template=V1PodTemplateSpec(
                spec=V1PodSpec(
                    containers=[
                        V1Container(
                            name="nginx",
                            resources=V1ResourceRequirements(
                                requests={"cpu": "1", "memory": "2Gi"},
                                limits={"memory": "4Gi"},
                            ),
                        ),
                        V1Container(
                            name="php",
                            resources=V1ResourceRequirements(
                                requests={"cpu": "4", "memory": "8Gi"}, limits={}
                            ),
                        ),
                        V1Container(name="php-monitor"),
                    ]
                )
            ),
        ),
    )

    mock_func1.return_value = deployment1_output, True
    mock_func2.return_value = {"cpu": 2, "memory": 2}
    mock_func3.return_value = 60
    mock_func4.return_value = True

    result = main.optimize_deployment(deployment1_input)

    assert (
        "k8soptimizer.arvato-aws.io/old-resources" in result.metadata.annotations.keys()
    )
    assert (
        "k8soptimizer.arvato-aws.io/last-update" in result.metadata.annotations.keys()
    )


def test_parse_args_version(capsys):
    args = ["--version"]
    with pytest.raises(SystemExit) as excinfo:
        main.parse_args(args)

    captured = capsys.readouterr()
    assert "k8soptimizer" in captured.out
    assert excinfo.value.code == 0


@patch("k8soptimizer.main.optimize_deployment")
@patch("k8soptimizer.main.verify_kubernetes_connection")
@patch("k8soptimizer.main.verify_prometheus_connection")
@patch("k8soptimizer.main.get_deployments")
@patch("k8soptimizer.main.get_namespaces")
def test_main(mock_func1, mock_func2, mock_func3, mock_func4, mock_func5):
    # Define a list of V1Namespace objects
    namespace1 = V1Namespace(metadata=V1ObjectMeta(name="namespace1"))
    namespace2 = V1Namespace(metadata=V1ObjectMeta(name="namespace2"))
    namespace_list = V1NamespaceList(items=[namespace1, namespace2])

    # Define a list of V1Namespace objects
    deployment1 = V1Deployment(
        metadata=V1ObjectMeta(
            name="deployment1",
            namespace="default",
        ),
        spec=V1DeploymentSpec(
            replicas=1,
            selector=V1LabelSelector(match_labels={"app": "nginx"}),
            template=V1PodTemplateSpec(
                spec=V1PodSpec(
                    containers=[
                        V1Container(
                            name="nginx",
                            resources=V1ResourceRequirements(
                                requests={"cpu": "1"}, limits={"cpu": "1"}
                            ),
                        )
                    ]
                )
            ),
        ),
    )
    deployment2 = V1Deployment(
        metadata=V1ObjectMeta(
            name="deployment2",
            namespace="default",
        ),
        spec=V1DeploymentSpec(
            replicas=2,
            selector=V1LabelSelector(match_labels={"app": "nginx"}),
            template=V1PodTemplateSpec(
                spec=V1PodSpec(
                    containers=[
                        V1Container(
                            name="nginx",
                            resources=V1ResourceRequirements(limits={"cpu": "2"}),
                        )
                    ]
                )
            ),
        ),
    )
    deployment3 = V1Deployment(
        metadata=V1ObjectMeta(
            name="deployment3",
        ),
        spec=V1DeploymentSpec(
            replicas=0,
            selector=V1LabelSelector(match_labels={"app": "nginx"}),
            template=V1PodTemplateSpec(
                spec=V1PodSpec(
                    containers=[
                        V1Container(
                            name="nginx",
                            resources=V1ResourceRequirements(limits={"cpu": "1"}),
                        )
                    ]
                )
            ),
        ),
    )
    deployment_list = V1DeploymentList(items=[deployment1, deployment2, deployment3])

    mock_func1.return_value = namespace_list
    mock_func2.return_value = deployment_list
    mock_func3.return_value = True
    mock_func4.return_value = True
    mock_func5.return_value = True

    main.stats["old_cpu_sum"] = 100
    main.stats["new_cpu_sum"] = 150
    main.stats["old_memory_sum"] = 1000
    main.stats["new_memory_sum"] = 2000

    main.main([])


@patch("k8soptimizer.main.query_prometheus")
def test_get_oom_killed_history(mock_func1):
    # Define your test data and expected response
    namespace_name = "test_namespace"
    deployment_name = "test_deployment"
    container_name = "test_container"

    mock_func1.return_value = {"data": {"result": [{"value": [0, 1]}]}}

    # Call the function under test
    result = main.get_oom_killed_history(
        namespace_name, deployment_name, container_name
    )

    # Verify that the function behaves as expected
    assert result == 1  # Check if the result is as expected

    mock_func1.return_value = {"data": {"result": [{"value": [0, 0]}]}}

    # Call the function under test
    result = main.get_oom_killed_history(
        namespace_name, deployment_name, container_name
    )

    # Verify that the function behaves as expected
    assert result == 0  # Check if the result is as expected


# calculate_lookback_minutes_from_deployment


test_data_optimize_container = [
    # Test case 0: Normal case
    {
        "request": main.MIN_MEMORY_REQUEST + 1,
        "limit": round((main.MIN_MEMORY_REQUEST + 1) * main.MEMORY_LIMIT_RATIO),
    },
    # Test case 1: Too low values
    {"request": 1024**2 * 1, "limit": main.MIN_MEMORY_LIMIT},
    # Test case 2: Too high values
    {"request": 1024**3 * 999999, "limit": main.MAX_MEMORY_LIMIT},
    # Test case 3: Too high values
    {"request": main.MAX_MEMORY_LIMIT + 1024, "limit": main.MAX_MEMORY_LIMIT},
]


@pytest.mark.parametrize("test_case", test_data_optimize_container)
def test_calculate_memory_limits(test_case):
    # Define your test data and expected response
    namespace_name = "test_namespace"
    deployment_name = "test_deployment"

    # Call the function under test
    result = main.calculate_memory_limits(
        namespace_name, deployment_name, "development", "nginx", test_case["request"]
    )

    # Verify that the function behaves as expected
    assert result == test_case["limit"]
