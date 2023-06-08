#!/command/with-contenv bashio
# ==============================================================================
# Emulated Hue
# This file defines environment variables based on user specified config options
# This overrides native environment variables with options.json
# ==============================================================================


if bashio::fs.file_exists '/data/options.json'; then

  if bashio::config.has_value 'data'; then
      echo $(bashio::config 'data') > /run/s6/container_environment/DATA_DIR
  fi

  if bashio::config.has_value 'http_port'; then
      echo $(bashio::config 'http_port') > /run/s6/container_environment/HTTP_PORT
  fi

  if bashio::config.has_value 'https_port'; then
      echo $(bashio::config 'https_port') > /run/s6/container_environment/HTTPS_PORT
  fi

  if bashio::config.has_value 'token'; then
      echo $(bashio::config 'token') > /run/s6/container_environment/HASS_TOKEN
  fi

  if bashio::config.has_value 'url'; then
      echo $(bashio::config 'url') > /run/s6/container_environment/HASS_URL
  fi

  if bashio::config.has_value 'use_default_ports_for_discovery'; then
      echo $(bashio::config 'use_default_ports_for_discovery') > /run/s6/container_environment/USE_DEFAULT_PORTS
  fi

  if bashio::config.has_value 'verbose'; then
      echo $(bashio::config 'verbose') > /run/s6/container_environment/VERBOSE
  fi

fi