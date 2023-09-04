import logging
import requests
import os
import json

from k8soptimizer import __version__

__author__ = "Philipp Hellmich"
__copyright__ = "Philipp Hellmich"
__license__ = "MIT"

PROMETHEUS_URL = os.getenv("PROMETHEUS_URL", "http://localhost:9090")

class PrometheusQuery:
    def __init__(self, config={}):
        self._config = config
        # self.setup_logging(self._args.loglevel)
        self.logger = logging.getLogger(__name__)
        self.logger.warn("init from prom")

    def query(self, query):
        logging.debug(query)
        response = requests.get(
            PROMETHEUS_URL + "/api/v1/query", params={"query": query}
        )
        j = json.loads(response.text)
        logging.debug(j)
        return j

    def get_max_pods_per_deployment_history(
        self,
        namespace_name,
        deployment_name,
        history_days="7d",
        quantile_over_time="0.95",
    ):
        query = 'max(quantile_over_time({quantile_over_time}, kube_deployment_spec_replicas{{job="kube-state-metrics", namespace="{namespace_name}", deployment="{deployment_name}"}}[{history_days}]))'.format(
            quantile_over_time=quantile_over_time,
            namespace_name=namespace_name,
            deployment_name=deployment_name,
            history_days=history_days,
        )
        j = self.query(query)

        if j["data"]["result"] == []:
            raise RuntimeError("No data found for prometheus query: {}".format(query))
        return int(j["data"]["result"][0]["value"][1])

    def get_cpu_cores_usage_history(
        self,
        namespace,
        workload,
        container,
        workload_type="deployment",
        history_days="7d",
        quantile_over_time="0.95",
    ):
        query = 'quantile_over_time({quantile_over_time}, kube_workload_container_resource_usage_cpu_cores_avg{{namespace="{namespace}", workload="{workload}", workload_type="{workload_type}", container="{container}"}}[{history_days}])'.format(
            quantile_over_time=quantile_over_time,
            namespace=namespace,
            workload=workload,
            workload_type=workload_type,
            container=container,
            history_days=history_days,
        )
        j = self.query(query)

        if j["data"]["result"] == []:
            raise RuntimeError("No data found for prometheus query: {}".format(query))
        return float(j["data"]["result"][0]["value"][1])

    def get_memory_bytes_usage_history(
        self,
        namespace,
        workload,
        container,
        workload_type="deployment",
        history_days="7d",
        quantile_over_time="0.95",
    ):
        query = 'quantile_over_time({quantile_over_time}, kube_workload_container_resource_usage_memory_bytes_max{{namespace="{namespace}", workload="{workload}", workload_type="{workload_type}", container="{container}"}}[{history_days}])'.format(
            quantile_over_time=quantile_over_time,
            namespace=namespace,
            workload=workload,
            workload_type=workload_type,
            container=container,
            history_days=history_days,
        )
        j = self.query(query)

        if j["data"]["result"] == []:
            raise RuntimeError("No data found for prometheus query: {}".format(query))
        return float(j["data"]["result"][0]["value"][1])

    def is_nodejs_container(
        self, namespace, workload, container, workload_type="deployment"
    ):
        query = 'count(nodejs_version_info{{container="{container}"}} * on(namespace,pod) group_left(workload, workload_type) namespace_workload_pod:kube_pod_owner:relabel{{workload="{workload}", workload_type="{workload_type}", namespace="{namespace}"}}) by (namespace, workload, workload_type, container)'.format(
            namespace=namespace,
            workload=workload,
            workload_type=workload_type,
            container=container,
        )
        j = self.query(query)

        if j["data"]["result"] == []:
            return False

        if float(j["data"]["result"][0]["value"][1]) > 0:
            return True

        return False
