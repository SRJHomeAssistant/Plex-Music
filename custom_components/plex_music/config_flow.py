"""Plex Music config flow and music library options."""

from __future__ import annotations

import ipaddress

from plexapi.myplex import MyPlexPinLogin
from plexapi.server import PlexServer
import voluptuous as vol

from homeassistant import config_entries
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import selector

from .const import CONF_MUSIC_LIBRARIES, CONF_PLEX_TOKEN, CONF_PLEX_URL, DOMAIN

from .library import get_music_libraries
from .alexa_setup import validate_public_https_url, validate_skill_id
from .alexa_wizard import country_console_info, interaction_model_json, skill_endpoint_url
from .voice_aliases import CONF_VOICE_ALIASES, save_voice_aliases
from .alexa_devices import CONF_ALEXA_PENDING_DEVICES, CONF_ALEXA_REGISTERED_DEVICES, register_devices, delete_devices

CONF_ALEXA_VOICE_CONFIRMATION = "alexa_voice_confirmation"
CONF_ALEXA_SKILL_ID = "alexa_skill_id"
CONF_ALEXA_ENDPOINT_URL = "alexa_endpoint_url"
CONF_ALEXA_SETUP_MODE = "alexa_setup_mode"


def _server_address(address: str) -> str:
    """Accept a private IPv4 address using Plex's default port."""
    ip = ipaddress.IPv4Address(address.strip())
    if not ip.is_private:
        raise ValueError("A private LAN IPv4 address is required")
    return f"http://{ip}:32400"


class PlexMusicConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Guide the user through Plex account authorisation."""

    VERSION = 1

    def __init__(self) -> None:
        """Set up per-flow authentication state."""
        self._server_url: str | None = None
        self._login: MyPlexPinLogin | None = None
        self._auth_url: str | None = None

    @staticmethod
    def async_get_options_flow(config_entry):
        """Provide an options flow for an existing Plex connection."""
        return PlexMusicOptionsFlow(config_entry)

    async def async_step_user(self, user_input=None):
        """Ask only for the local Plex server IPv4 address."""
        errors = {}
        if user_input is not None:
            try:
                self._server_url = _server_address(user_input["plex_ip"])
            except ValueError:
                errors["base"] = "invalid_ip"
            else:
                try:
                    self._login = await self.hass.async_add_executor_job(
                        lambda: MyPlexPinLogin(oauth=True)
                    )
                    self._auth_url = await self.hass.async_add_executor_job(
                        self._login.oauthUrl
                    )
                except Exception:
                    errors["base"] = "auth_unavailable"
                else:
                    return await self.async_step_authorize()

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema({vol.Required("plex_ip"): str}),
            errors=errors,
        )

    async def async_step_authorize(self, user_input=None):
        """Confirm Plex authorisation and register the local server."""
        if self._login is None or self._server_url is None:
            return await self.async_step_user()

        errors = {}
        if user_input is not None:
            try:
                authorised = await self.hass.async_add_executor_job(
                    self._login.checkLogin
                )
            except Exception:
                errors["base"] = "auth_unavailable"
            else:
                if not authorised or not self._login.token:
                    errors["base"] = "not_authorized"
                else:
                    token = self._login.token
                    try:
                        server = await self.hass.async_add_executor_job(
                            PlexServer, self._server_url, token
                        )
                        machine_id = server.machineIdentifier
                        name = server.friendlyName
                    except Exception:
                        errors["base"] = "cannot_connect"
                    else:
                        await self.async_set_unique_id(machine_id)
                        self._abort_if_unique_id_configured()
                        return self.async_create_entry(
                            title=name,
                            data={
                                CONF_PLEX_URL: self._server_url,
                                CONF_PLEX_TOKEN: token,
                            },
                        )

        return self.async_show_form(
            step_id="authorize",
            data_schema=vol.Schema({}),
            description_placeholders={"auth_url": self._auth_url or ""},
            errors=errors,
        )


class PlexMusicOptionsFlow(config_entries.OptionsFlow):
    """Select music libraries from the connected Plex server."""

    def __init__(self, config_entry):
        """Keep the config entry for supported HA versions."""
        self._entry = config_entry
        self._pending_alexa_options = None

    async def async_step_init(self, user_input=None):
        """Discover available music libraries and save the selection."""
        errors = {}
        try:
            libraries = await self.hass.async_add_executor_job(
                get_music_libraries,
                self._entry.data[CONF_PLEX_URL],
                self._entry.data[CONF_PLEX_TOKEN],
            )
        except Exception:
            libraries = {}
            errors["base"] = "cannot_connect"

        if not errors and not libraries:
            errors["base"] = "no_music_libraries"

        selected = list(
            self._entry.options.get(CONF_MUSIC_LIBRARIES, libraries.keys())
        )
        selected = [key for key in selected if key in libraries]

        if user_input is not None and user_input.get("next_step") == "alexa":
            return await self.async_step_alexa()
        if user_input is not None and user_input.get("next_step") == "devices":
            return await self.async_step_alexa_devices()
        if user_input is not None and user_input.get("next_step") == "delete_voice_aliases":
            return await self.async_step_delete_voice_aliases()
        if user_input is not None and user_input.get("next_step") == "voice_aliases":
            return await self.async_step_voice_aliases()
        if user_input is not None and user_input.get("next_step") == "delete_devices":
            return await self.async_step_alexa_delete_devices()

        if user_input is not None and not errors:
            requested = user_input[CONF_MUSIC_LIBRARIES]
            if not requested:
                errors["base"] = "select_library"
            elif not set(requested).issubset(libraries):
                errors["base"] = "invalid_selection"
            else:
                return self.async_create_entry(
                    title="",
                    data={
                        **self._entry.options,
                        CONF_MUSIC_LIBRARIES: requested,
                    },
                )

        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema(
                {
                    vol.Required(
                        CONF_MUSIC_LIBRARIES, default=selected
                    ): cv.multi_select(libraries),
                    vol.Required("next_step", default="save"): vol.In({
                        "save": "Save selected music libraries",
                        "alexa": "Alexa skill setup and instructions",
                        "devices": "Register and name Echo devices",
                        "delete_devices": "Delete registered Alexa devices",
                        "voice_aliases": "Edit voice recognition overrides",
                        "delete_voice_aliases": "Delete voice recognition overrides",
                    }),
                }
            ),
            errors=errors,
        )

    async def async_step_alexa(self, user_input=None):
        """Choose whether to register an existing skill or prepare a new skill."""
        if user_input is not None:
            if user_input["setup_mode"] == "existing":
                return await self.async_step_alexa_existing()
            return await self.async_step_alexa_new()
        return self.async_show_form(
            step_id="alexa",
            data_schema=vol.Schema({
                vol.Required("setup_mode", default="new"): vol.In({
                    "new": "Set up a new Alexa skill",
                    "existing": "Use an existing Alexa skill ID",
                })
            }),
        )

    async def async_step_alexa_existing(self, user_input=None):
        """Store an existing Alexa skill ID and its public endpoint URL."""
        return await self._async_alexa_details(user_input, "alexa_existing", "existing")

    async def async_step_alexa_new(self, user_input=None):
        """Prepare the URL for a skill created in Amazon's developer console."""
        return await self._async_alexa_details(user_input, "alexa_new", "new")

    async def _async_alexa_details(self, user_input, step_id, mode):
        """Validate and persist skill metadata without claiming skill deployment."""
        errors = {}
        suggested_url = (self.hass.config.external_url or "").rstrip("/")
        current_confirmation = self._entry.options.get(CONF_ALEXA_VOICE_CONFIRMATION, False)
        if user_input is not None:
            chosen_url = (suggested_url if user_input["url_source"] == "home_assistant" else user_input.get("endpoint_url", ""))
            try:
                endpoint = validate_public_https_url(chosen_url)
            except ValueError:
                errors["endpoint_url"] = "invalid_endpoint"
            skill_id = user_input.get("skill_id", "").strip()
            if skill_id:
                try:
                    validate_skill_id(skill_id)
                except ValueError:
                    errors["skill_id"] = "invalid_skill_id"
            elif mode == "existing":
                errors["skill_id"] = "required_skill_id"
            if not errors:
                self._pending_alexa_options = {
                    **self._entry.options,
                    CONF_ALEXA_SETUP_MODE: mode,
                    CONF_ALEXA_SKILL_ID: skill_id,
                    CONF_ALEXA_ENDPOINT_URL: endpoint,
                    CONF_ALEXA_VOICE_CONFIRMATION: user_input["voice_confirmation"],
                }
                return await self.async_step_alexa_instructions()
        return self.async_show_form(
            step_id=step_id,
            data_schema=vol.Schema({
                vol.Required("url_source", default="home_assistant" if suggested_url else "custom"): vol.In({
                    "home_assistant": "Use Home Assistant external URL",
                    "custom": "Enter my own public HTTPS URL",
                }),
                vol.Required("voice_confirmation", default=current_confirmation): bool,
                vol.Optional(
                    "endpoint_url",
                    default=self._entry.options.get(CONF_ALEXA_ENDPOINT_URL, suggested_url),
                ): str,
                vol.Optional(
                    "skill_id",
                    default=self._entry.options.get(CONF_ALEXA_SKILL_ID, ""),
                ): str,
            }),
            errors=errors,
            description_placeholders={"external_url": suggested_url or "Not configured"},
        )

    async def async_step_alexa_instructions(self, user_input=None):
        """Display the model and console instructions before saving settings."""
        options = self._pending_alexa_options
        if options is None:
            return await self.async_step_alexa()
        if user_input is not None:
            self._pending_alexa_options = None
            return self.async_create_entry(title="", data=options)

        country = getattr(self.hass.config, "country", None)
        console_url, locale = country_console_info(country)
        endpoint = skill_endpoint_url(options[CONF_ALEXA_ENDPOINT_URL])
        return self.async_show_form(
            step_id="alexa_instructions",
            data_schema=vol.Schema({
                vol.Required("developer_console_url", default=console_url): str,
                vol.Required("suggested_locale", default=locale): str,
                vol.Required("proposed_endpoint_url", default=endpoint): str,
                vol.Optional("interaction_model_json", default=interaction_model_json()): str,
            }),
            description_placeholders={
                "console_url": console_url,
                "country": country or "Not configured",
                "locale": locale,
                "endpoint_url": endpoint,
            },
        )

    async def async_step_alexa_devices(self, user_input=None):
        """Assign friendly names to discovered Alexa devices."""
        pending = dict(self._entry.options.get(CONF_ALEXA_PENDING_DEVICES, {}))
        registered = dict(self._entry.options.get(CONF_ALEXA_REGISTERED_DEVICES, {}))
        if not pending:
            return self.async_show_form(
                step_id="alexa_devices",
                data_schema=vol.Schema({}),
                description_placeholders={"pending_count": "0", "registered_count": str(len(registered))},
            )
        errors = {}
        if user_input is not None:
            selected = user_input.get("devices", [])
            names = {key: user_input.get(f"name_{key}", "") for key in selected}
            if not names:
                errors["base"] = "select_device"
            else:
                try:
                    updated = register_devices(dict(self._entry.options), names)
                except ValueError:
                    errors["base"] = "invalid_device_name"
                else:
                    return self.async_create_entry(title="", data=updated)
        fields = {
            vol.Required("devices", default=[]): cv.multi_select({
                key: f"New Echo {i + 1} ({key[:8]})"
                for i, key in enumerate(pending)
            }),
        }
        for i, key in enumerate(pending):
            fields[vol.Optional(f"name_{key}", default=f"Echo {i + 1}")] = str
        return self.async_show_form(
            step_id="alexa_devices",
            data_schema=vol.Schema(fields),
            errors=errors,
            description_placeholders={
                "pending_count": str(len(pending)),
                "registered_count": str(len(registered)),
            },
        )

    async def async_step_alexa_delete_devices(self, user_input=None):
        """Remove selected Echos and their Home Assistant device entries."""
        registered = dict(self._entry.options.get(CONF_ALEXA_REGISTERED_DEVICES, {}))
        if not registered:
            return self.async_show_form(
                step_id="alexa_delete_devices",
                data_schema=vol.Schema({}),
                description_placeholders={"registered_count": "0"},
            )
        if user_input is not None:
            keys = user_input.get("devices_to_delete", [])
            if keys:
                try:
                    updated = delete_devices(dict(self._entry.options), keys)
                except ValueError:
                    return self.async_show_form(
                        step_id="alexa_delete_devices",
                        data_schema=vol.Schema({
                            vol.Required("devices_to_delete", default=[]):
                                cv.multi_select({key: device["name"] for key, device in registered.items()}),
                        }),
                        errors={"base": "invalid_selection"},
                        description_placeholders={"registered_count": str(len(registered))},
                    )
                registry = dr.async_get(self.hass)
                for key in keys:
                    device = registry.async_get_device(
                        identifiers={(DOMAIN, f"{self._entry.entry_id}_alexa_{key}")}
                    )
                    if device:
                        registry.async_remove_device(device.id)
                return self.async_create_entry(title="", data=updated)
        return self.async_show_form(
            step_id="alexa_delete_devices",
            data_schema=vol.Schema({
                vol.Required("devices_to_delete", default=[]):
                    cv.multi_select({key: device["name"] for key, device in registered.items()}),
            }),
            description_placeholders={"registered_count": str(len(registered))},
        )

    async def async_step_voice_aliases(self, user_input=None):
        """Manage editable speech-to-catalogue overrides."""
        errors = {}
        if user_input is not None:
            try:
                updated = save_voice_aliases(
                    dict(self._entry.options), user_input["overrides"]
                )
            except ValueError:
                errors["base"] = "invalid_voice_aliases"
            else:
                return self.async_create_entry(title="", data=updated)
        existing = self._entry.options.get(CONF_VOICE_ALIASES, {})
        initial = "\n".join(f"{heard} = {target}" for heard, target in existing.items())
        return self.async_show_form(
            step_id="voice_aliases",
            data_schema=vol.Schema({
                vol.Required("overrides", default=initial): selector.TextSelector(
                    selector.TextSelectorConfig(multiline=True)
                ),
            }),
            errors=errors,
        )

    async def async_step_delete_voice_aliases(self, user_input=None):
        """Remove chosen voice mappings without retyping the others."""
        aliases = dict(self._entry.options.get(CONF_VOICE_ALIASES, {}))
        if not aliases:
            return self.async_abort(reason="no_voice_aliases")
        if user_input is not None:
            selected = user_input.get("aliases_to_delete", [])
            if not selected or not set(selected).issubset(aliases):
                errors = {"base": "invalid_selection"}
            else:
                updated = dict(self._entry.options)
                updated[CONF_VOICE_ALIASES] = {
                    key: value for key, value in aliases.items() if key not in selected
                }
                return self.async_create_entry(title="", data=updated)
        else:
            errors = {}
        return self.async_show_form(
            step_id="delete_voice_aliases",
            data_schema=vol.Schema({
                vol.Required("aliases_to_delete", default=[]): cv.multi_select({
                    key: f"{key} → {value}" for key, value in aliases.items()
                }),
            }),
            errors=errors,
        )
