#!/command/with-contenv bashio
# ==============================================================================
# Emulated Hue
# This file installs the Emulated Hue version if specified
# ==============================================================================

declare release_version

if bashio::config.has_value 'tag_commit_or_branch'; then
    release_version=$(bashio::config 'tag_commit_or_branch')
else
    release_version=${TAG_COMMIT_OR_BRANCH:-master}
fi

colon_count=$(tr -dc ':' <<<"$release_version" | awk '{ print length; }')
repo_name="core"

if [[ "$colon_count" == 1 ]]; then
  IFS=':' read -r -a array <<< "$release_version"
  username=${array[0]}
  ref=${array[1]}
elif [ "$colon_count" == 2 ]; then
  IFS=':' read -r -a array <<< "$release_version"
  username=${array[0]}
  repo_name=${array[1]}
  ref=${array[2]}
else
  username="hass-emulated-hue"
  ref=$release_version
fi
full_url="https://github.com/${username}/${repo_name}/archive/${ref}.tar.gz"
bashio::log.info "Installing Emulated Hue version '${release_version}' (${full_url})..."
curl -Lo /tmp/emulator.tar.gz "${full_url}"
mkdir -p /tmp/emulator
tar zxvf /tmp/emulator.tar.gz --strip 1 -C /tmp/emulator
mv /tmp/emulator/emulated_hue /app
bashio::log.info "Installed successfully!"
