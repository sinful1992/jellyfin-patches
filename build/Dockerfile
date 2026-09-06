# Overlay a patched Jellyfin server onto the stock LinuxServer image.
#
# Only the assemblies our patches touch are replaced. Everything else -- s6 init,
# jellyfin-web, ffmpeg, the volume layout -- comes from the stock image unchanged,
# and the assembly version stays 10.11.11 so ABI-pinned plugins (Intro Skipper)
# keep loading.
ARG BASE_IMAGE=lscr.io/linuxserver/jellyfin:10.11.11ubu2604-ls43
FROM ${BASE_IMAGE}

ARG PATCH_REV=unknown
# image.source links the GHCR package to the repo, so the package page shows the
# README and inherits the repo's provenance instead of standing alone.
LABEL org.opencontainers.image.source="https://github.com/sinful1992/jellyfin-patches"
LABEL org.opencontainers.image.url="https://github.com/sinful1992/jellyfin-patches"
LABEL org.opencontainers.image.description="Jellyfin with local patches (${PATCH_REV})"
LABEL local.jellyfin.patched="true"
LABEL local.jellyfin.patch-rev="${PATCH_REV}"

COPY dll/ /usr/lib/jellyfin/bin/
