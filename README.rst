.. These are examples of badges you might want to add to your README:
   please update the URLs accordingly

    .. image:: https://api.cirrus-ci.com/github/<USER>/k8soptimizer.svg?branch=main
        :alt: Built Status
        :target: https://cirrus-ci.com/github/<USER>/k8soptimizer
    .. image:: https://readthedocs.org/projects/k8soptimizer/badge/?version=latest
        :alt: ReadTheDocs
        :target: https://k8soptimizer.readthedocs.io/en/stable/
    .. image:: https://img.shields.io/pypi/v/k8soptimizer.svg
        :alt: PyPI-Server
        :target: https://pypi.org/project/k8soptimizer/
    .. image:: https://img.shields.io/conda/vn/conda-forge/k8soptimizer.svg
        :alt: Conda-Forge
        :target: https://anaconda.org/conda-forge/k8soptimizer
    .. image:: https://pepy.tech/badge/k8soptimizer/month
        :alt: Monthly Downloads
        :target: https://pepy.tech/project/k8soptimizer
    .. image:: https://img.shields.io/twitter/url/http/shields.io.svg?style=social&label=Twitter
        :alt: Twitter
        :target: https://twitter.com/k8soptimizer

.. image:: https://img.shields.io/badge/-PyScaffold-005CA0?logo=pyscaffold
    :alt: Project generated with PyScaffold
    :target: https://pyscaffold.org/
.. image:: https://img.shields.io/coveralls/github/arvatoaws-labs/k8soptimizer/main.svg
    :alt: Coveralls
    :target: https://coveralls.io/r/arvatoaws-labs/k8soptimizer

|

============
k8soptimizer
============


    This tool optimizes the kubernetes workloads resource requsts and limits.

Say goodbye to resource underutilization and hello to a more efficient Kubernetes experience. Try *k8soptimizer* today and see the difference for yourself!


Description
-----------

Optimizing Kubernetes resource management has never been more efficient! *k8soptimizer* empowers you to fine-tune your deployments, ensuring optimal performance and resource allocation. Leverage Prometheus metrics to make data-driven decisions, dynamically adjusting resource requests and limits for unprecedented efficiency.

This tool can run once or on a regular schedule (eg. every 2 oder 4 hours) and will adjust the resource requests and limits of your deployments based on the historical resource utilization data from prometheus.


Features
--------

- Supports static and dynamic deployments (hpa)
    - static deployments get more resources assigned because they cannot scale out
    - dynamic deployments get less resources assigned because they can scale out
- Support for cpu and memory resources
    - The CPU requests are calculated based on a specified percentile of the sum of CPU allocations across all pods.
    - Memory requests are determined by a specified percentile of memory usage, calculated from the average memory utilization across all pods.
    - Memory limits are set based on a specified percentile of memory usage, derived from the maximum memory utilization across all pods.
- Analyze historical resource utilization data using prometheus as a data source
    - Queries based on quantile over time which can be adjusted
    - Look back one week and predict the resource utilization for the hours
    - Look back 4 hours and compared it to one week ago to get a trend
- Automatically adjust deployment requests
    - Increases memory requests and limits upon discovering OOM kills.
    - Caps requests to 1 core for Node.js applications.
    - Eliminates CPU limits following best practices (see https://home.robusta.dev/blog/stop-using-cpu-limits)
    - Provides flexibility with various thresholds and configurable settings. (see configuration)
- Highly tested code using the Pytest framework.
- Can be executed as a Docker image.
- Supports configuration through environment variables.

Differences between VPA
--------

- Supports running together wtih hpa (they won't fight each other)
- Supports lower memory requests (there is no 256MB minimum as default)
- Forecasts todays with data from one week ago in order to account for different usage pattern based on weekdays
- Compares the last 4 hours with data from the last 4 hours a week ago in order to detect a trend
- Updates the deployment object instead of the crated pod
- Can also run as a cli command outside of the cluster

Known issues
--------

- Flux or other management might rollback the changes

Future ideas
--------

- Helm Chart to run the k8skoptimizer as a cronjob in k8s
- Support for auto discovery of additional runtimes whith specific limitations (python does not consume more than 1 core)
- Support for jvm discovery, maybe the memory request can be reduced (right now a java app would not lower memory consumption because it takes all it can get)
- Support for statefulesets and daemonsets
- Support for kubernetes events (to see oom kills and others useful events)
- Store recommendations in a configmap and use it for helm deployment
- Dynamic configuration based on namespace or object annotations
- Admission controller mode
- Better logging and alerting

Quickstart
==========

    # cli mode

    # install prometheus operator

    # apply rules from contrib folder

    kubectl apply -f contrib/prometheus-rules.yaml

    # port forward prometheus

    kubectl port-forward -n monitoring service/prometheus-operator-kube-p-prometheus 9090:9090

    # run k8soptimizer

    python3 src/k8soptimizer/main.py -n default -v --dry-run

    # Modify the configuration to your needs
    export NAMESPACE_PATTERN="default"

    # cluster mode


    # install rbac permissions

    kubectl apply -f deploy/rbac.yaml

    # modify config.yaml to your needs

    kubectl apply -f deploy/config.yaml

    # deploy the cronjob

    kubectl apply -f deploy/cronjob.yaml

    # trigger the cronjob manually or wait for the next schedule
    # verify the logs of the cronjob


Configuration
=============

The following environment variables can be used to configure the behavior of k8soptimizer.

PROMETHEUS_URL
--------------

- Default: `http://localhost:9090`
- Description: The URL of the Prometheus server used to query resource utilization metrics.

NAMESPACE_PATTERN
------------------

- Default: `.*`
- Description: A regular expression pattern to filter namespaces for optimization.

DEPLOYMENT_PATTERN
-------------------

- Default: `.*`
- Description: A regular expression pattern to filter deployments for optimization.

CONTAINER_PATTERN
-------------------

- Default: `.*`
- Description: A regular expression pattern to filter container names for optimization.

PROMETHEUS_URL
-------------------

- Default: `http://localhost:9090`
- Description: The URL for the Prometheus server.

DEFAULT_LOOKBACK_MINUTES
-------------------

- Default: `240` (4 hours)
- Description: The default lookback time in minutes for queries.

DEFAULT_OFFSET_MINUTES
-------------------

- Default: Computed based on a week minus DEFAULT_LOOKBACK_MINUTES.
- Description: The default offset in minutes for queries.

DEFAULT_QUANTILE_OVER_TIME
-------------------

- Default: `0.95`
- Description: The default quantile value for queries. A higher value will result in more resources being allocated.

DEFAULT_QUANTILE_OVER_TIME_STATIC_CPU
-------------------

- Default: `0.95`
- Description: Default quantile value for CPU static configurations. A higher value will result in more resources being allocated.

DEFAULT_QUANTILE_OVER_TIME_HPA_CPU
-------------------

- Default: `0.7`
- Description: Default quantile value for CPU Horizontal Pod Autoscaler (HPA). A higher value will result in more resources being allocated.

DEFAULT_QUANTILE_OVER_TIME_STATIC_MEMORY
-------------------

- Default: `0.95`
- Description: Default quantile value for memory static configurations. A higher value will result in more resources being allocated.

DEFAULT_QUANTILE_OVER_TIME_HPA_MEMORY
-------------------

- Default: `0.8`
- Description: Default quantile value for memory Horizontal Pod Autoscaler (HPA). A higher value will result in more resources being allocated.

DRY_RUN_MODE
-------------------

- Default: `False`
- Description: Flag for dry run mode.

MIN_CPU_REQUEST
-------------------

- Default: `0.010`
- Description: Minimum CPU request value.

MAX_CPU_REQUEST
-------------------

- Default: `16`
- Description: Maximum CPU request value.

MAX_CPU_REQUEST_NODEJS
-------------------

- Default: `1.0`
- Description: Maximum CPU request value specifically for Node.js.

CPU_REQUEST_RATIO
-------------------

- Default: `1.0`
- Description: CPU request ratio. Increase this value to allocate more CPU resources than historical usage.

MIN_MEMORY_REQUEST
-------------------

- Default: `16 MB` (1024**2 * 16)
- Description: Minimum memory request value in bytes.

MAX_MEMORY_REQUEST
-------------------

- Default: `16 GB` (1024**3 * 16)
- Description: Maximum memory request value in bytes.

MEMORY_REQUEST_RATIO
-------------------

- Default: `1.5`
- Description: Memory request ratio. Increase this value to allocate more memory resources than historical usage.

MEMORY_LIMIT_RATIO
-------------------

- Default: `2.0`
- Description: Memory limit ratio. Increase this value to allow more memory resources than historical usage.

MIN_MEMORY_LIMIT
-------------------

- Default: `16 MB` (1024**2 * 16)
- Description: Minimum memory limit value in bytes.

MAX_MEMORY_LIMIT
-------------------

- Default: `16 GB` (1024**3 * 16)
- Description: Maximum memory limit value in bytes.

CHANGE_THRESHOLD
-------------------

- Default: `0.1`
- Description: Threshold for change.

HPA_TARGET_REPLICAS_RATIO
-------------------

- Default: `0.1`
- Description: Ratio for Horizontal Pod Autoscaler (HPA) target replicas. This value is limited by the hpa min and max settings. A setting of 0 would result in having only min pods running, a setting of 1 would result in having max pods running.

TREND_LOOKBOOK_MINUTES
-------------------

- Default: `240` (4 hours)
- Description: Trend lookback time in minutes.

TREND_OFFSET_MINUTES
-------------------

- Default: `10080` (7 days)
- Description: Trend offset in minutes.

TREND_MAX_RATIO
-------------------

- Default: `1.5`
- Description: Maximum ratio for trends.

TREND_MIN_RATIO
-------------------

- Default: `0.5`
- Description: Minimum ratio for trends.

TREND_QUANTILE_OVER_TIME
-------------------

- Default: `0.8`
- Description: Quantile value for trends.

LOG_LEVEL
-------------------

- Default: `INFO`
- Description: Logging level.

LOG_FORMAT
-------------------

- Default: `json`
- Description: Logging format.
