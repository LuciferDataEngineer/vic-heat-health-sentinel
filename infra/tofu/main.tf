# Same local broker as infra/docker-compose.yml, described for OpenTofu.
# Do not apply this and compose at the same time: both bind port 9092.

terraform {
  required_version = ">= 1.6.0"
  required_providers {
    docker = {
      source  = "kreuzwerker/docker"
      version = "3.0.2"
    }
  }
}

provider "docker" {}

resource "docker_image" "redpanda" {
  name = "docker.redpanda.com/redpandadata/redpanda:v24.3.6"
}

resource "docker_container" "redpanda" {
  name    = "vhhs-redpanda"
  image   = docker_image.redpanda.image_id
  command = [
    "redpanda", "start",
    "--overprovisioned",
    "--smp", "1",
    "--memory", "512M",
    "--reserve-memory", "0M",
    "--node-id", "0",
    "--check=false",
    "--kafka-addr", "PLAINTEXT://0.0.0.0:9092",
    "--advertise-kafka-addr", "PLAINTEXT://localhost:9092",
  ]
  env = ["REDPANDA_AUTO_CREATE_TOPICS=true"]
  ports {
    internal = 9092
    external = 9092
  }
}
