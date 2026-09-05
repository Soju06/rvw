#!/bin/sh
# Both images pass the same pinned release arguments to this build-only helper.
set -eu

: "${GH_VERSION:?GH_VERSION is required}"
: "${GH_SHA256:?GH_SHA256 is required}"
: "${MIN_GH_VERSION:?MIN_GH_VERSION is required}"
gh_version="${GH_VERSION#v}"
gh_archive="gh_${gh_version}_linux_amd64.tar.gz"
gh_checksums="gh_${gh_version}_checksums.txt"
gh_release_url="https://github.com/cli/cli/releases/download/${GH_VERSION}"
gh_build_dir="$(mktemp -d)"
trap 'rm --recursive --force "$gh_build_dir"' EXIT
cd "$gh_build_dir"

curl --fail --location --silent --show-error --output "$gh_archive" "${gh_release_url}/${gh_archive}"
curl --fail --location --silent --show-error --output "$gh_checksums" "${gh_release_url}/${gh_checksums}"
grep --fixed-strings --line-regexp "${GH_SHA256}  ${gh_archive}" "$gh_checksums"
printf '%s  %s\n' "$GH_SHA256" "$gh_archive" > expected.sha256
sha256sum --check expected.sha256
tar --extract --gzip --file="$gh_archive"
install --mode=0755 "gh_${gh_version}_linux_amd64/bin/gh" /usr/local/bin/gh
gh --version
installed_version="$(gh --version)"
installed_version="${installed_version#gh version }"
installed_version="${installed_version%% *}"
test "${installed_version}" = "${gh_version}"
dpkg --compare-versions "${installed_version}" ge "${MIN_GH_VERSION}"
