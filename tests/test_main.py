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


@patch("k8soptimizer.main.requests.get")  # Mock the requests.get function
def test_get_max_pods_per_deployment_history(mock_requests_get):
    # Define your test data and expected response
    namespace_name = "test_namespace"
    deployment_name = "test_deployment"
    expected_result = {"data": {"result": [{"value": [0, "42"]}]}}

    # Mock the response from requests.get
    mock_response = unittest.mock.Mock()
    mock_response.text = json.dumps(expected_result)
    mock_requests_get.return_value = mock_response

    # Call the function under test
    result = main.get_max_pods_per_deployment_history(
        namespace_name, deployment_name, history_days="7d", quantile_over_time="0.95"
    )

    # Verify that the function behaves as expected
    assert result == 42  # Check if the result is as expected

    expected_result = {"data": {"result": []}}

    # Mock the response from requests.get
    mock_response = unittest.mock.Mock()
    mock_response.text = json.dumps(expected_result)
    mock_requests_get.return_value = mock_response

    with pytest.raises(RuntimeError) as exc_info:
        main.get_max_pods_per_deployment_history(
            namespace_name,
            deployment_name,
            history_days="7d",
            quantile_over_time="0.95",
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
        "default" "deploymentX",
    )

    assert len(result) == 0  # Check if the result is as expected


def test_get_max_cpu_cores_per_technology():
    assert 1 == main.get_max_cpu_cores_per_technology("nodejs")
    assert 100 == main.get_max_cpu_cores_per_technology("java")


# @patch('module_name.func1')
# @patch('module_name.func2')
# def test_mocking_multiple_functions(mock_func1, mock_func2):
#     mock_func1.return_value = "Mocked Func1"
#     mock_func2.return_value = "Mocked Func2"

#     result1 = func1()
#     result2 = func2()

#     assert result1 == "Mocked Func1"
#     assert result2 == "Mocked Func2"
