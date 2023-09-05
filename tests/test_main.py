import pytest
import json
import unittest

# Standard library imports...
from unittest.mock import Mock, patch

from kubernetes.client.models import *

import k8soptimizer.main as main

__author__ = "Philipp Hellmich"
__copyright__ = "Philipp Hellmich"
__license__ = "MIT"


# def test_fib():
#     """API Tests"""
#     assert fib(1) == 1
#     assert fib(2) == 1
#     assert fib(7) == 13
#     with pytest.raises(AssertionError):
#         fib(-10)


# def test_main(capsys):
#     """CLI Tests"""
#     # capsys is a pytest fixture that allows asserts against stdout/stderr
#     # https://docs.pytest.org/en/stable/capture.html
#     main(["7"])
#     captured = capsys.readouterr()
#     assert "The 7-th Fibonacci number is 13" in captured.out

@patch("k8soptimizer.main.query_prometheus")  # Mock the requests.get function
def test_query_prometheus(mock_requests_get):
    # Define your test data and expected response
    expected_result = {"data": {"result": [{"value": [0, "42"]}]}}

    # Mock the response from requests.get
    mock_response = unittest.mock.Mock()
    mock_response.text = json.dumps(expected_result)
    mock_requests_get.return_value = mock_response

    # Call the function under test
    result = main.query_promtheus("node_load1")

    # Verify that the function behaves as expected
    assert result == {"data": {"result": [{"value": [0, "42"]}]}}  # Check if the result is as expected

def test_get_cpu_cores_usage_history():
    """API Tests"""

    # # Call the service to hit the mocked API.
    # with patch('project.services.requests.get') as mock_get:
    #     mock_get.return_value.ok = True
    #     mock_get.return_value.json.return_value = [{
    #         'userId': 1,
    #         'id': 1,
    #         'title': 'Make the bed',
    #         'completed': False
    #     }]

    #     mocked = get_todos()
    #     mocked_keys = mocked.json().pop().keys()

    assert True == True
    # assert 1 == main.get_cpu_cores_usage_history('default', 'nginx-deployment', 'nginx')


@patch("k8soptimizer.main.query_prometheus")
@patch("k8soptimizer.main.get_max_pods_per_deployment_history")
def test_get_max_pods_per_deployment_history(mock_func1, mock_func2):
    # Define your test data and expected response
    namespace_name = "test_namespace"
    deployment_name = "test_deployment"

    mock_func1.return_value = {"data": {"result": [{"value": [0, "42"]}]}}
    mock_func2.return_value = 42

    # Call the function under test
    result = main.get_max_pods_per_deployment_history(
        namespace_name, deployment_name, lookback_minutes=3600*7*24, quantile_over_time=0.95
    )

    # Verify that the function behaves as expected
    assert result == mock_func2.return_value  # Check if the result is as expected

    mock_func1.return_value = {"data": {"result": []}}
    mock_func2.return_value = None

    with pytest.raises(RuntimeError) as exc_info:
        main.get_max_pods_per_deployment_history(
            namespace_name,
            deployment_name,
            lookback_minutes=3600*24*7,
            quantile_over_time=0.95,
        )

    # Check the exception message or other attributes if needed
    assert "No data found" in str(exc_info.value)


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
    assert len(result) == 2  # Check if the result is as expected

    # Define a list of V1Namespace objects
    namespace_list = V1NamespaceList(items=[namespace1])

    mock_requests_get.return_value = namespace_list

    # Call the function under test
    result = main.get_namespaces("namespace1")

    assert len(result) == 1  # Check if the result is as expected
    assert result[0].metadata.name == "namespace1"  # Check if the result is as expected

    # Call the function under test
    result = main.get_namespaces("namespaceX")

    assert len(result) == 0  # Check if the result is as expected


@patch(
    "k8soptimizer.main.client.AppsV1Api.list_namespaced_deployment"
)  # Mock the requests.get function
def test_get_deployments(mock_requests_get):
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
                        )
                    ]
                )
            ),
        ),
    )
    deployment2 = V1Deployment(
        metadata=V1ObjectMeta(
            name="deployment2",
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
    assert len(result) == 2  # Check if the result is as expected

    # Define a list of V1Namespace objects
    deployment_list = V1DeploymentList(items=[deployment1, deployment2])

    mock_requests_get.return_value = deployment_list

    # Call the function under test
    result = main.get_deployments("default", "^deployment1$")

    assert len(result) == 1  # Check if the result is as expected
    assert (
        result[0].metadata.name == "deployment1"
    )  # Check if the result is as expected

    # Call the function under test
    result = main.get_deployments(
        "default", "deploymentX"
    )

    assert len(result) == 0  # Check if the result is as expected


@patch(
    "k8soptimizer.main.client.AutoscalingV2Api.list_namespaced_horizontal_pod_autoscaler"
)  # Mock the requests.get function
def test_get_hpa_for_deployment(mock_requests_get):
    hpa1 = V2HorizontalPodAutoscaler(
        metadata=V1ObjectMeta(
            name="deployment1"
        ),
        spec=V2HorizontalPodAutoscalerSpec(
            max_replicas=10,
            min_replicas=1,
            metrics=[
                V2MetricSpec(
                    type="Resource",
                    resource=V2ResourceMetricSource(
                        name="cpu",
                        target=V2MetricTarget(average_utilization=80,type='Utilization')
                    )
                )
            ],
            scale_target_ref=V2CrossVersionObjectReference(
                kind="Deployment",
                name="deployment1"
            )
        )
    )

    hpa2 = V2HorizontalPodAutoscaler(
        metadata=V1ObjectMeta(
            name="deployment2"
        ),
        spec=V2HorizontalPodAutoscalerSpec(
            max_replicas=10,
            min_replicas=1,
            metrics=[
                V2MetricSpec(
                    type="Resource",
                    resource=V2ResourceMetricSource(
                        name="cpu",
                        target=V2MetricTarget(average_utilization=80,type='Utilization')
                    )
                )
            ],
            scale_target_ref=V2CrossVersionObjectReference(
                kind="Deployment",
                name="deployment2"
            )
        )
    )
    hpa_list = V2HorizontalPodAutoscalerList(items=[hpa1, hpa2])

    mock_requests_get.return_value = hpa_list

    # Call the function under test
    result = main.get_hpa_for_deployment("default", "deployment1")

    assert result is not None

    assert result.metadata.name == "deployment1"



test_data_hpa = [
    # Test case 0: Normal case
    {
        "input_params": {
            "avg_cpu": 100,
            "avg_memory": 100,
            "min_replicas": 1,
            "max_replicas": 10,
            "pod_replica_history": 3,
        },
        "expected_output": {
            "ratio_cpu": 1,
            "ratio_memory": 1
        }
    },

    # Test case 1: Expected to raise CPU ratio to match HPA
    {
        "input_params": {
            "avg_cpu": 80,
            "min_replicas": 1,
            "max_replicas": 10,
            "pod_replica_history": 3,
        },
        "expected_output": {
            "ratio_cpu": 1.25,
            "ratio_memory": 1
        }
    },

    # Test case 2: Expected to raise memory ratio to match HPA
    {
        "input_params": {
            "avg_memory": 80,
            "min_replicas": 1,
            "max_replicas": 10,
            "pod_replica_history": 3,
        },
        "expected_output": {
            "ratio_cpu": 1,
            "ratio_memory": 1.25
        }
    },

    # Test case 3: Expected to raise both CPU and memory ratio to match HPA
    {
        "input_params": {
            "avg_cpu": 80,
            "avg_memory": 80,
            "min_replicas": 1,
            "max_replicas": 10,
            "pod_replica_history": 3,
        },
        "expected_output": {
            "ratio_cpu": 1.25,
            "ratio_memory": 1.25
        }
    },

    # Test case 4: Expected to raise CPU because of max_replicas reached
    {
        "input_params": {
            "avg_cpu": 100,
            "min_replicas": 1,
            "max_replicas": 10,
            "pod_replica_history": 10,
        },
        "expected_output": {
            "ratio_cpu": 2,
            "ratio_memory": 1
        }
    },

    # Test case 5: Expected to raise CPU because is almost max_replicas reached
    {
        "input_params": {
            "avg_cpu": 100,
            "min_replicas": 1,
            "max_replicas": 10,
            "pod_replica_history": 9,
        },
        "expected_output": {
            "ratio_cpu": 1.89,
            "ratio_memory": 1
        }
    },

    # Test case 6: Expected to raise CPU ratio because max_replicas is reached
    {
        "input_params": {
            "avg_cpu": 100,
            "avg_memory": 100,
            "min_replicas": 1,
            "max_replicas": 10,
            "pod_replica_history": 3,
            "pod_oom_history": 5
        },
        "expected_output": {
            "ratio_cpu": 1,
            "ratio_memory": 2
        }
    },

    # Test case 7: Expected to raise CPU and memory ratio because almost max_replicas is reached and ooms werde found
    {
        "input_params": {
            "avg_cpu": 100,
            "avg_memory": 100,
            "min_replicas": 1,
            "max_replicas": 10,
            "pod_replica_history": 3,
            "pod_oom_history": 5
        },
        "expected_output": {
            "ratio_cpu": 1,
            "ratio_memory": 2
        }
    },

    # Test case 8: Expected to raise both CPU and memory ratio to match HPA even if history is 0
    {
        "input_params": {
            "avg_cpu": 80,
            "avg_memory": 80,
            "min_replicas": 1,
            "max_replicas": 10,
            "pod_replica_history": 0,
            "pod_oom_history": 0
        },
        "expected_output": {
            "ratio_cpu": 1.25,
            "ratio_memory": 1.25
        }
    },
]

@pytest.mark.parametrize("test_case", test_data_hpa)
@patch("k8soptimizer.main.get_oom_killed_history")
@patch("k8soptimizer.main.get_max_pods_per_deployment_history")
@patch("k8soptimizer.main.get_hpa_for_deployment")
def test_calculate_hpa_target_ratio(mock_func1, mock_func2, mock_func3, test_case):

    # Extract input parameters and expected output from the test case
    input_params = test_case["input_params"]
    expected_output = test_case["expected_output"]

    metrics = []
    if "avg_memory" in input_params:
        metrics.append(
            V2MetricSpec(
                type="Resource",
                resource=V2ResourceMetricSource(
                    name="memory",
                    target=V2MetricTarget(average_utilization=input_params['avg_memory'],type='Utilization')
                )
            )
        )
    if "avg_cpu" in input_params:
        metrics.append(
            V2MetricSpec(
                type="Resource",
                resource=V2ResourceMetricSource(
                    name="cpu",
                    target=V2MetricTarget(average_utilization=input_params['avg_cpu'],type='Utilization')
                )
            )
        )


    hpa1 = V2HorizontalPodAutoscaler(
        metadata=V1ObjectMeta(
            name="deployment1"
        ),
        spec=V2HorizontalPodAutoscalerSpec(
            max_replicas=input_params['max_replicas'],
            min_replicas=input_params['min_replicas'],
            metrics=metrics,
            scale_target_ref=V2CrossVersionObjectReference(
                kind="Deployment",
                name="deployment1"
            )
        )
    )

    mock_func1.return_value = hpa1
    mock_func2.return_value = input_params['pod_replica_history']
    mock_func3.return_value = 0
    if "pod_oom_history" in input_params:
        mock_func3.return_value = input_params['pod_oom_history']

    # Call the function under test
    result = main.calculate_hpa_target_ratio("default", "deployment1")

    assert result["cpu"] == pytest.approx(expected_output["ratio_cpu"], rel=1e-2)
    assert result["memory"] == pytest.approx(expected_output["ratio_memory"], rel=1e-2)


test_data_cpu = [
    # Test case 0: Normal case
    {
        "input_params": {
            "cpu_history": main.CPU_MIN + 1,
            "cpu_ratio": 1,
            "runtime": None
        },
        "expected_output": main.CPU_MIN + 1
    },

    # Test case 1: Below min cpu
    {
        "input_params": {
            "cpu_history": 0.000001,
            "cpu_ratio": 1,
            "runtime": None
        },
        "expected_output": main.CPU_MIN
    },

    # Test case 2: Below min cpu
    {
        "input_params": {
            "cpu_history": 1,
            "cpu_ratio": 0.000001,
            "runtime": None
        },
        "expected_output": main.CPU_MIN
    },

    # Test case 3: Higher max cpu
    {
        "input_params": {
            "cpu_history": 9999999999,
            "cpu_ratio": 1,
            "runtime": None
        },
        "expected_output": main.CPU_MAX
    },

    # Test case 4: Higher max cpu
    {
        "input_params": {
            "cpu_history": 1,
            "cpu_ratio": 9999999999,
            "runtime": None
        },
        "expected_output": main.CPU_MAX
    },

    # Test case 5: nodejs
    {
        "input_params": {
            "cpu_history": 10,
            "cpu_ratio": 9999999999,
            "runtime": "nodejs"
        },
        "expected_output": main.CPU_MAX_NODEJS
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

    mock_func1.return_value = input_params['cpu_history']
    mock_func2.return_value = None

    input_params = test_case["input_params"]
    expected_output = test_case["expected_output"]

    if "runtime" in input_params:
        mock_func2.return_value = input_params['runtime']

    # Call the function under test
    result = main.calculate_cpu_requests(
        namespace_name, deployment_name, "development", "nginx", input_params['cpu_ratio']
    )

    assert result == pytest.approx(expected_output, rel=1e-2)



test_data_memory = [
    # Test case 0: Normal case
    {
        "input_params": {
            "memory_history": main.MEMORY_MIN + 1024,
            "memory_ratio": 1,
            "runtime": None
        },
        "expected_output": main.MEMORY_MIN + 1024
    },

    # Test case 1: Below min memory
    {
        "input_params": {
            "memory_history": 0.000001,
            "memory_ratio": 1,
            "runtime": None
        },
        "expected_output": main.MEMORY_MIN
    },

    # Test case 2: Below min memory
    {
        "input_params": {
            "memory_history": 1,
            "memory_ratio": 000000.1,
            "runtime": None
        },
        "expected_output": main.MEMORY_MIN
    },

    # Test case 3: Higher max memory
    {
        "input_params": {
            "memory_history": 999999999999999,
            "memory_ratio": 1,
            "runtime": None
        },
        "expected_output": main.MEMORY_MAX
    },

    # Test case 4: Higher max memory
    {
        "input_params": {
            "memory_history": 1,
            "memory_ratio": 999999999999999,
            "runtime": None
        },
        "expected_output": main.MEMORY_MAX
    },

    # Test case 5: nodejs
    {
        "input_params": {
            "memory_history": 10,
            "memory_ratio": 999999999999999,
            "runtime": "nodejs"
        },
        "expected_output": main.MEMORY_MAX
    },
]

@pytest.mark.parametrize("test_case", test_data_memory)
@patch("k8soptimizer.main.discover_container_runtime")
@patch("k8soptimizer.main.get_memory_bytes_usage_history")
def test_calculate_memory_requests(mock_func1, mock_func2, test_case):
    namespace_name = "test_namespace"
    deployment_name = "test_deployment"
    input_params = test_case["input_params"]
    expected_output = test_case["expected_output"]

    mock_func1.return_value = input_params['memory_history']
    mock_func2.return_value = None

    if "runtime" in input_params:
        mock_func2.return_value = input_params['runtime']

    # Call the function under test
    result = main.calculate_memory_requests(
        namespace_name, deployment_name, "development", "nginx", input_params['memory_ratio']
    )

    assert result == pytest.approx(expected_output, rel=1e-2)
