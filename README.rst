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


Features
--------

- Analyze historical resource utilization data using prometheus as a data source
    - Dynamic lookback time based on deployment age and last optimization
    - Queries based on quantile over time which can be adjusted
- Automatically adjust deployment requests
    - Use hpa average_utilization setting to calculate a normalized utilization
        - Scenario 1: 10 pods requesting 0.8 cores and consuming 0.8 cores with 80% HPA average_utilization results in 100% normalized utilization.
        - Scenario 2: 10 pods requesting 1 core and consuming 0.5 cores with 80% HPA average_utilization results in 62.5% normalized utilization.
        - Scenario 3: 10 pods requesting 1 core and consuming 1 core with 100% HPA average_utilization results in 100% normalized utilization.
        - Scenario 4: 10 pods requesting 1 core and consuming 1 core with 100% HPA average_utilization results in 50% normalized utilization.
    - Increase requests if hpa limit is almost reached
        - Example: In Scenario 1, where HPA limits are (min=1, max=10, current=10), and the deployment requests 0.5 cores while consuming 0.5 cores, the CPU core request is increased to 1 to stay below the maximum replicas.
    - Increase memory request if discoverd oom kiils
    - Limit requests to 1 core for nodejs applications
    - Remove requests all cpu limits (see https://home.robusta.dev/blog/stop-using-cpu-limits)
    - Support for various thresholds and settings (see configuration)
- Highly tested code using pytest framework
- Can run as docker image
- Supports environment variables for configuration

Differences between VPA
--------

- Supports running together wtih hpa (they won't fight each other)
- Supports lower memory requests (there is no 256MB minimum)
- Supports normalized utilization
- Updates the deployment object instead of the crated pod
- Can run as a cli command outside of the cluster

Known issues
--------

- Flux or other management might rollback the changes
- Change of CPU_REQUEST_RATIO or MEMORY_REQUEST_RATIO will only work if hpa is not used with the corresponding metric
    - if you want to have more cpu headroom in a hpa usecase ensure that the target average utilization is set to a lower value like 80% or less
    - if you want to have more memory headroom in a hpa usecase ensure that the target average utilization is set to a lower value like 80% or less

Future ideas
--------

- Helm Chart to run the k8skoptimizer as a cronjob in k8s
- Support for auto discovery of additional runtimes whith specific limitations (python does not consume more than 1 core)
- Support for jvm discovery, maybe the memory request can be reduced (right now a java app would not lower memory consumption because it takes all it can get)
- Support for statefulesets and daemonsets
- Support for kubernetes events (to see oom kills and others useful events)
- Dynamic configuration based on namespace or object annotations
- Admission Controller mode
- Better logging and alerting

Quickstart
==========


    # install prometheus operator

    # apply rules from contrib folder

    kubectl apply -f contrib/prometheus-rules.yaml

    # port forward prometheus

    kubectl port-forward -n monitoring service/prometheus-operator-kube-p-prometheus 9090:9090

    # run k8soptimizer

    python3 src/k8soptimizer/main.py -n default -v --dry-run


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
------------------

- Default: `.*`
- Description: A regular expression pattern to filter containers for optimization.

CREATE_AGE_THRESHOLD
---------------------

- Default: `60`
- Description: The threshold (in minutes) for considering a new deployment for optimization.

UPDATE_AGE_THRESHOLD
---------------------

- Default: `60`
- Description: The threshold (in minutes) for considering an updated deployment for optimization.

MIN_LOOKBACK_MINUTES
---------------------

- Default: `30`
- Description: The minimum lookback time (in minutes) for historical data.

MAX_LOOKBACK_MINUTES
---------------------

- Default: `2592000` (30 days)
- Description: The maximum lookback time (in minutes) for historical data.

OFFSET_LOOKBACK_MINUTES
-----------------------

- Default: `5`
- Description: The offset applied to the lookback time (in minutes).

DEFAULT_LOOKBACK_MINUTES
------------------------

- Default: `604800` (7 days)
- Description: The default lookback time (in minutes) for historical data.

DEFAULT_QUANTILE_OVER_TIME
--------------------------

- Default: `0.95`
- Description: The default quantile used when querying metrics over time. (max value is 1.0, a higher value will result in higher resource requests)

DRY_RUN_MODE
------------

- Default: `False`
- Description: If set to `True`, the tool will run in dry-run mode and only simulate changes.

MIN_CPU_REQUEST
---------------

- Default: `0.010`
- Description: The minimum CPU request value (below `10m` may not work reliably with HPA).

MAX_CPU_REQUEST
---------------

- Default: `16`
- Description: The maximum CPU request value.

MAX_CPU_REQUEST_NODEJS
----------------------

- Default: `1.0`
- Description: The maximum CPU request value for Node.js applications.

CPU_REQUEST_RATIO
-------------------

- Default: `1.0`
- Description: The ratio used to calculate cpu requests. (changing this might break the normalized utilization calculation and will cause problems with hpa)

MIN_MEMORY_REQUEST
-------------------

- Default: `16777216` (16 MiB)
- Description: The minimum memory request value (in bytes).

MAX_MEMORY_REQUEST
-------------------

- Default: `17179869184` (16 GiB)
- Description: The maximum memory request value (in bytes).

MEMORY_REQUEST_RATIO
-------------------

- Default: `1.0`
- Description: The ratio used to calculate memory requests. (changing this might break the normalized utilization calculation and will cause problems with hpa)

MEMORY_LIMIT_RATIO
-------------------

- Default: `1.5`
- Description: The ratio used to calculate memory limits based on memory requests.

MIN_MEMORY_LIMIT
-----------------

- Default: Calculated based on `MIN_MEMORY_REQUEST` and `MEMORY_LIMIT_RATIO`.
- Description: The minimum memory limit value (in bytes).

MAX_MEMORY_LIMIT
-----------------

- Default: Calculated based on `MAX_MEMORY_REQUEST` and `MEMORY_LIMIT_RATIO`.
- Description: The maximum memory limit value (in bytes).

CHANGE_THRESHOLD
----------------

- Default: `0.1`
- Description: The threshold used to determine if a change in resources is significant.
