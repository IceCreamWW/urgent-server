Here's a refined version of the README file for the project:

---

# Project Overview

This project is built upon the [CodaLab Competitions](https://github.com/codalab/codalab-competitions) framework and has been customized to utilize PSC as the evaluation server. The following diagram illustrates the workflow:

![Pipeline](images/pipeline.png)

# Quick Start Guide

The project is deployed at [https://ears.urgent-challenge.com](https://ears.urgent-challenge.com). An administrator account has been created for access:

- **Username**: urgent
- **Password**: g3!yD3CWNbf7gzdu

You can visit the competition page directly at: [Competition Page](https://ears.urgent-challenge.com/competitions/1)

For more detailed information, refer to the [CodaLab Documentation](https://github.com/codalab/codalab-competitions/wiki).

## Accessing the Urgent Server

To access the urgent server, follow these steps:

1. Copy the file `examples/urgent.pem` to `~/.ssh/urgent.pem`
2. Add the following configuration to your `~/.ssh/config` file:
    ```bash
    Host urgent
        HostName 52.26.172.172
        User ubuntu
        Port 22
        IdentityFile ~/.ssh/urgent.pem
    ```
3. The urgent EARS project is located at `/home/ubuntu/workspace/urgent-ears`.

# Tutorials

## Create a New Competition

To create a new competition, you need to set up a new evaluation task queue and a Celery worker.

1. Go to [Worker Queue Management](https://ears.urgent-challenge.com/queues/) and create a new queue.
2. Copy the broker URL, add a new worker to `docker-compose.yml`, and run `docker compose up -d`. Below is an example configuration for a new worker. Replace 'ears.urgent-challenge.com' in the broker URL with 'rabbit' since we will only access the broker within the Docker network.
3. Update the `TRACK` parameter to match the track used by the PSC evaluation program.
4. [Prepare the evaluation dataset on PSC](#prepare-an-evaluation-dataset-on-psc)
5. Upload the competition bundle for the new competition. An example bundle is available at `examples/competition.zip`.

```yaml
worker_ears:
  build:
    context: worker
    dockerfile: Dockerfile
  restart: unless-stopped
  env_file: .env
  environment:
    - TRACK=ears
    - BROKER_URL=pyamqp://7f541161-6af6-43a3-821c-4332006d7a97:40754acf-6723-49b9-b81f-ef06fa7b5106@rabbit:5672/394337fa-550b-47e3-bcf5-2c32e4e14baa
  hostname: worker_ears
  links:
    - rabbit
  logging:
    options:
      max-size: "200k"
  mem_limit: 1g
  memswap_limit: 1g
  container_name: worker-ears
```

## Prepare an Evaluation Dataset on PSC <a name="prepare-an-evaluation-dataset-on-psc"></a>

For the evaluation program, refer to `/ocean/projects/cis210027p/wwang13/workspace/urgent/evaluation`. Prepare a directory named `workspace/<track>/assets`. Refer to the EARS track as an example.

```bash
workspace/ears/assets/
|-- models
|   |-- model_v8.onnx -> /ocean/projects/cis210027p/wzhangn/espnet_urgent2024/egs2/urgent24/enh1/urgent2024_challenge/DNSMOS/DNSMOS/model_v8.onnx
|   `-- sig_bak_ovr.onnx -> /ocean/projects/cis210027p/wzhangn/espnet_urgent2024/egs2/urgent24/enh1/urgent2024_challenge/DNSMOS/DNSMOS/sig_bak_ovr.onnx
`-- reference
    |-- clean
    `-- spk1.scp
```

