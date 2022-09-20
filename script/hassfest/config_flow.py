"""Generate config flow file."""
from __future__ import annotations

import json
import pathlib

import black

from .brand import validate as validate_brands
from .model import Brand, Config, Integration
from .serializer import to_string

BASE = """
\"\"\"Automatically generated by hassfest.

To update, run python3 -m script.hassfest
\"\"\"

FLOWS = {}
""".strip()

UNIQUE_ID_IGNORE = {"huawei_lte", "mqtt", "adguard"}


def validate_integration(config: Config, integration: Integration):
    """Validate config flow of an integration."""
    config_flow_file = integration.path / "config_flow.py"

    if not config_flow_file.is_file():
        if integration.manifest.get("config_flow"):
            integration.add_error(
                "config_flow",
                "Config flows need to be defined in the file config_flow.py",
            )
        return

    config_flow = config_flow_file.read_text()

    needs_unique_id = integration.domain not in UNIQUE_ID_IGNORE and (
        "async_step_discovery" in config_flow
        or "async_step_bluetooth" in config_flow
        or "async_step_hassio" in config_flow
        or "async_step_homekit" in config_flow
        or "async_step_mqtt" in config_flow
        or "async_step_ssdp" in config_flow
        or "async_step_zeroconf" in config_flow
        or "async_step_dhcp" in config_flow
        or "async_step_usb" in config_flow
    )

    if not needs_unique_id:
        return

    has_unique_id = (
        "self.async_set_unique_id" in config_flow
        or "self._async_handle_discovery_without_unique_id" in config_flow
        or "register_discovery_flow" in config_flow
        or "AbstractOAuth2FlowHandler" in config_flow
    )

    if has_unique_id:
        return

    if config.specific_integrations:
        notice_method = integration.add_warning
    else:
        notice_method = integration.add_error

    notice_method(
        "config_flow", "Config flows that are discoverable need to set a unique ID"
    )


def generate_and_validate(integrations: dict[str, Integration], config: Config):
    """Validate and generate config flow data."""
    domains = {
        "integration": [],
        "helper": [],
    }

    for domain in sorted(integrations):
        integration = integrations[domain]

        if not integration.manifest or not integration.config_flow:
            continue

        validate_integration(config, integration)

        domains[integration.integration_type].append(domain)

    return black.format_str(BASE.format(to_string(domains)), mode=black.Mode())


def _populate_brand_integrations(
    integrations: dict[str, Integration],
    brand_metadata: dict,
    sub_integrations: list[str],
) -> None:
    """Add referenced integrations to a brand's metadata."""
    brand_metadata.setdefault("integrations", {})
    for domain in sub_integrations:
        integration = integrations.get(domain)
        if not integration:
            continue
        metadata = {}
        metadata["name"] = integration.name
        if integration.translated_name:
            metadata["translated_name"] = True
        brand_metadata["integrations"][domain] = metadata


def _generate_v2(
    brands: dict[str, Brand], integrations: dict[str, Integration], config: Config
):
    """Generate extended config flow data."""

    result = {
        "integration": {},
        "helper": {},
    }

    # Compile a set of integrations which are referenced from at least one brand's
    # integrations list. These integrations will not be present in the root level of the
    # generated config flow index.
    brand_integration_domains = {
        brand_integration_domain
        for brand in brands.values()
        for brand_integration_domain in brand.integrations or []
    }

    # Compile a set of integrations which are not referenced from any brand's
    # integrations list.
    primary_domains = {
        domain
        for domain, integration in integrations.items()
        if integration.manifest
        and integration.config_flow
        and domain not in brand_integration_domains
    }
    # Add all brands to the set
    primary_domains |= set(brands)

    # Generate the config flow index
    for domain in sorted(primary_domains):
        metadata = {}

        if brand := brands.get(domain):
            metadata["name"] = brand.name
            if brand.integrations:
                # Add the integrations which are referenced from the brand's
                # integrations list
                _populate_brand_integrations(integrations, metadata, brand.integrations)
            if brand.iot_standards:
                metadata["iot_standards"] = brand.iot_standards
            result["integration"][domain] = metadata
        else:  # integration
            integration = integrations[domain]
            metadata["name"] = integration.name
            if integration.translated_name:
                metadata["translated_name"] = True
            result[integration.integration_type][domain] = metadata

    return json.dumps(result, indent=2)


def validate(integrations: dict[str, Integration], config: Config):
    """Validate config flow file."""
    config_flow_path = config.root / "homeassistant/generated/config_flows.py"
    config_flow_v2_path = config.root / "homeassistant/generated/config_flows_v2.json"
    config.cache["config_flow"] = content = generate_and_validate(integrations, config)

    if config.specific_integrations:
        return

    brands = Brand.load_dir(pathlib.Path(config.root / "homeassistant/brands"), config)
    validate_brands(brands, integrations, config)

    with open(str(config_flow_path)) as fp:
        if fp.read() != content:
            config.add_error(
                "config_flow",
                "File config_flows.py is not up to date. "
                "Run python3 -m script.hassfest",
                fixable=True,
            )

    config.cache["config_flow_v2"] = content = _generate_v2(
        brands, integrations, config
    )
    with open(str(config_flow_v2_path)) as fp:
        if fp.read() != content + "\n":
            config.add_error(
                "config_flow",
                "File config_flows_v2.json is not up to date. "
                "Run python3 -m script.hassfest",
                fixable=True,
            )


def generate(integrations: dict[str, Integration], config: Config):
    """Generate config flow file."""
    config_flow_path = config.root / "homeassistant/generated/config_flows.py"
    config_flow_v2_path = config.root / "homeassistant/generated/config_flows_v2.json"
    with open(str(config_flow_path), "w") as fp:
        fp.write(f"{config.cache['config_flow']}")
    with open(str(config_flow_v2_path), "w") as fp:
        fp.write(f"{config.cache['config_flow_v2']}\n")
