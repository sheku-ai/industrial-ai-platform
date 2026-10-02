variable "REGISTRY" {
  default = "ghcr.io"
}

variable "NAMESPACE" {
  default = "industrial-ai-platform"
}

variable "VERSION" {
  default = "dev"
}

variable "REVISION" {
  default = "unknown"
}

variable "CREATED" {
  default = "unknown"
}

variable "PLATFORMS" {
  default = ["linux/amd64", "linux/arm64"]
}

group "default" {
  targets = ["api", "portal"]
}

target "common" {
  platforms = PLATFORMS
  attest = [
    "type=sbom",
    "type=provenance,mode=max",
  ]
  labels = {
    "org.opencontainers.image.title" = "SHEKU"
    "org.opencontainers.image.version" = VERSION
    "org.opencontainers.image.revision" = REVISION
    "org.opencontainers.image.created" = CREATED
    "org.opencontainers.image.source" = "https://github.com/sheku-ai/industrial-ai-platform"
    "org.opencontainers.image.licenses" = "Apache-2.0"
  }
}

target "api" {
  inherits = ["common"]
  context = "./apps/api"
  dockerfile = "Dockerfile"
  tags = [
    "${REGISTRY}/${NAMESPACE}/api:${VERSION}",
    "${REGISTRY}/${NAMESPACE}/api:${REVISION}",
  ]
}

target "portal" {
  inherits = ["common"]
  context = "."
  dockerfile = "apps/admin-portal/Dockerfile"
  tags = [
    "${REGISTRY}/${NAMESPACE}/portal:${VERSION}",
    "${REGISTRY}/${NAMESPACE}/portal:${REVISION}",
  ]
}
