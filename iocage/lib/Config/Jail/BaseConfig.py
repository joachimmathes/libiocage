# Copyright (c) 2014-2017, iocage
# All rights reserved.
#
# Redistribution and use in source and binary forms, with or without
# modification, are permitted providing that the following conditions
# are met:
# 1. Redistributions of source code must retain the above copyright
#    notice, this list of conditions and the following disclaimer.
# 2. Redistributions in binary form must reproduce the above copyright
#    notice, this list of conditions and the following disclaimer in the
#    documentation and/or other materials provided with the distribution.
#
# THIS SOFTWARE IS PROVIDED BY THE AUTHOR ``AS IS'' AND ANY EXPRESS OR
# IMPLIED WARRANTIES, INCLUDING, BUT NOT LIMITED TO, THE IMPLIED
# WARRANTIES OF MERCHANTABILITY AND FITNESS FOR A PARTICULAR PURPOSE
# ARE DISCLAIMED.  IN NO EVENT SHALL THE AUTHOR BE LIABLE FOR ANY
# DIRECT, INDIRECT, INCIDENTAL, SPECIAL, EXEMPLARY, OR CONSEQUENTIAL
# DAMAGES (INCLUDING, BUT NOT LIMITED TO, PROCUREMENT OF SUBSTITUTE GOODS
# OR SERVICES; LOSS OF USE, DATA, OR PROFITS; OR BUSINESS INTERRUPTION)
# HOWEVER CAUSED AND ON ANY THEORY OF LIABILITY, WHETHER IN CONTRACT,
# STRICT LIABILITY, OR TORT (INCLUDING NEGLIGENCE OR OTHERWISE) ARISING
# IN ANY WAY OUT OF THE USE OF THIS SOFTWARE, EVEN IF ADVISED OF THE
# POSSIBILITY OF SUCH DAMAGE.
import typing
import re

import iocage.lib.Config.Jail.JailConfigProperties
import iocage.lib.errors
import iocage.lib.helpers

# mypy
import iocage.lib.Logger


class BaseConfig(dict):
    """
    Represents an iocage jail's configuration

    A jail configuration can be loaded from various formats that were used
    by different versions of iocage. Technically it is possible to store
    set properties in deprecated formats, but this might break when using
    newer features than the legacy version of iocage supports. It is
    recommended to use the reading capabilities to migrate to the JSON
    config format.

    Supported Configuration Formats:

        JSON: (current)
            Since the Python 3 implementation iocage stored jail configs in
            a file called `config.json` within the jail's root dataset

        ZFS:
            iocage-legacy written in Bash used to save jail configurations
            as ZFS properties on the jail's root dataset. Due to poor
            performance and easier readability this format later was replaced
            with a file based config storage. Even though it is a deprecated
            format, libiocage is compatible to read a jail config from ZFS.

        UCL:
            Yet another deprecated configuration format, that libiocage also
            supports reading from. A legacy version of iocage used this format.

    Special Properties:

        Special properties are

    """

    special_properties: (
        'iocage.lib.Config.Jail.'
        'JailConfigProperties.JailConfigProperties'
    )
    data: typing.Dict[str, typing.Any]

    def __init__(
        self,
        logger: typing.Optional[iocage.lib.Logger.Logger]=None
    ) -> None:

        self.data = {}
        dict.__init__(self)

        self.logger = iocage.lib.helpers.init_logger(self, logger)

        tmp = iocage.lib.Config.Jail.JailConfigProperties
        self.special_properties = tmp.JailConfigProperties(
            config=self,
            logger=self.logger
        )

    def clone(
        self,
        data: typing.Dict[str, typing.Any],
        skip_on_error: bool=False
    ) -> None:
        """
        Apply data from a data dictionary to the JailConfig

        Existing jail configuration is not emptied using.

        Args:

            data (dict):
                Dictionary containing the configuration to apply

            skip_on_error (bool):
                Passed to __setitem__

        """
        if len(data.keys()) == 0:
            return

        current_id = self["id"]
        for key, value in data.items():

            if (key in ["id", "name", "uuid"]) and (current_id is not None):
                value = current_id

            self.__setitem__(key, value, skip_on_error=skip_on_error)

    def read(self, data: dict) -> None:

        # ignore name/id/uuid in config if the jail already has a name
        if self["id"] is not None:
            data_keys = data.keys()
            if "name" in data_keys:
                del data["name"]
            if "id" in data_keys:
                del data["id"]
            if "uuid" in data_keys:
                del data["uuid"]

        self.clone(data)

    def update_special_property(self, name: str) -> bool:
        try:
            self.data[name] = str(self.special_properties[name])
            return True
        except KeyError:
            return False

    def attach_special_property(self, name, special_property) -> None:
        self.special_properties[name] = special_property

    def _set_legacy(self, value, **kwargs) -> None:
        try:
            self.legacy = iocage.lib.helpers.parse_bool(value)
        except TypeError:
            self.legacy = False

    def _get_id(self) -> str:
        return str(self.data["id"])

    def _set_id(self, name: str, **kwargs) -> None:

        try:
            # We do not want to set the same name twice.
            # This can occur when the Jail is initialized
            # with it's name and the same name is read from
            # the configuration
            if self["id"] == name:
                return
        except KeyError:
            pass

        if name is None:
            self.data["id"] = None
            return

        allowed_characters_pattern = "([^A-z0-9\\._\\-]|\\^)"
        invalid_characters = re.findall(allowed_characters_pattern, name)
        if len(invalid_characters) > 0:
            msg = (
                f"Invalid character in name: "
                " ".join(invalid_characters)
            )
            self.logger.error(msg)
            raise iocage.lib.errors.InvalidJailName(logger=self.logger)

        is_valid_name = iocage.lib.helpers.validate_name(name)
        if is_valid_name is True:
            self.data["id"] = name
        else:
            if iocage.lib.helpers.is_uuid(name) is True:
                self.data["id"] = name
            else:
                raise iocage.lib.errors.InvalidJailName(logger=self.logger)

    def _get_name(self) -> str:
        return self._get_id()

    def _get_uuid(self) -> str:
        return self._get_id()

    def _get_type(self) -> str:

        if self["basejail"]:
            return "basejail"
        elif self["clonejail"]:
            return "clonejail"
        else:
            return "jail"

    def _set_type(self, value: typing.Optional[str], **kwargs) -> None:

        if value == "basejail":
            self["basejail"] = True
            self["clonejail"] = False
            self.data["type"] = "jail"

        elif value == "clonejail":
            self["basejail"] = False
            self["clonejail"] = True
            self.data["type"] = "jail"

        else:
            self.data["type"] = value

    def _get_priority(self) -> int:
        return int(self.data["priority"])

    def _set_priority(self, value: typing.Union[int, str], **kwargs) -> None:
        self.data["priority"] = str(value)

    # legacy support
    def _get_tag(self) -> typing.Optional[str]:

        if self._has_legacy_tag is True:
            return str(self.data["tag"])

        try:
            return str(self["tags"][0])
        except KeyError:
            return None

    def _set_tag(self, value: str, **kwargs) -> None:

        if (self._has_legacy_tag is True) or ("tags" not in self.data.keys()):
            # store as deprecated `tag` for downwards compatibility
            # setting `tags` overrides usage of the deprecated `tag` property
            self.data["tag"] = value
            return

        tags = self["tags"]
        if value in tags:
            # remove the tag if it was existing
            del tags[tags.index(value)]

        tags.insert(0, value)
        self.data["tags"] = iocage.lib.helpers.to_string(tags)

    @property
    def _has_legacy_tag(self) -> bool:
        return "tag" in self.data.keys()

    def _get_tags(self) -> typing.List[str]:
        return list(iocage.lib.helpers.parse_list(self.data["tags"]))

    def _set_tags(
        self,
        value: typing.Union[
            str,
            bool,
            int,
            typing.List[typing.Union[str, bool, int]]
        ],
        **kwargs
    ) -> None:

        data = iocage.lib.helpers.to_string(value)
        self.data["tags"] = data

        if self._has_legacy_tag is True:
            del self.data["tag"]

    def _get_basejail(self) -> bool:
        return iocage.lib.helpers.parse_bool(self.data["basejail"]) is True

    def _set_basejail(self, value: typing.Any, **kwargs) -> None:
        self.data["basejail"] = self.stringify(value)

    def _get_clonejail(self) -> bool:
        return iocage.lib.helpers.parse_bool(self.data["clonejail"]) is True

    def _set_clonejail(
        self,
        value: typing.Optional[typing.Union[str, bool]],
        **kwargs
    ) -> None:
        self.data["clonejail"] = self.stringify(value)

    def _get_defaultrouter(self) -> typing.Optional[str]:
        value = self.data['defaultrouter']
        return str(value) if (value != "none" and value is not None) else None

    def _set_defaultrouter(
        self,
        value: typing.Optional[str],
        **kwargs
    ) -> None:
        if value is None:
            value = 'none'
        self.data['defaultrouter'] = value

    def _get_defaultrouter6(self) -> typing.Optional[str]:
        value = self.data['defaultrouter6']
        return str(value) if (value != "none" and value is not None) else None

    def _set_defaultrouter6(
        self,
        value: typing.Optional[str],
        **kwargs
    ) -> None:
        if value is None:
            value = 'none'
        self.data['defaultrouter6'] = value

    def _get_vnet(self) -> bool:
        return iocage.lib.helpers.parse_user_input(self.data["vnet"]) is True

    def _set_vnet(
        self,
        value: typing.Union[str, bool],
        **kwargs
    ) -> None:
        self.data["vnet"] = iocage.lib.helpers.to_string(
            value,
            true="on",
            false="off"
        )

    def _get_jail_zfs_dataset(self) -> typing.List[str]:
        try:
            jail_zfs_dataset = str(self.data["jail_zfs_dataset"])
            return jail_zfs_dataset.split()
        except KeyError:
            return []

    def _set_jail_zfs_dataset(
        self,
        value: typing.Union[typing.List[str], str],
        **kwargs
    ) -> None:

        value = [value] if isinstance(value, str) else value
        self.data["jail_zfs_dataset"] = " ".join(value)

    def _get_jail_zfs(self):
        return iocage.lib.helpers.parse_user_input(
            self.data["jail_zfs"]
        )

    def _set_jail_zfs(self, value, **kwargs):
        parsed_value = iocage.lib.helpers.parse_user_input(value)
        if parsed_value is None:
            del self.data["jail_zfs"]
            return
        self.data["jail_zfs"] = iocage.lib.helpers.to_string(
            parsed_value,
            true="on",
            false="off"
        )

    def _get_cloned_release(self) -> typing.Optional[str]:
        try:
            return str(self.data["cloned_release"])
        except KeyError:
            release = self["release"]
            if isinstance(release, str):
                return str(self["release"])
            return None

    def _get_basejail_type(self) -> typing.Optional[str]:

        # first see if basejail_type was explicitly set
        if "basejail_type" in self.data.keys():
            return str(self.data["basejail_type"])

        # if it was not, the default for is 'nullfs' if the jail is a basejail
        try:
            if self["basejail"]:
                return "nullfs"
        except KeyError:
            pass

        # otherwise the jail does not have a basejail_type
        return None

    def _get_login_flags(self):
        try:
            return JailConfigList(self.data["login_flags"].split())
        except KeyError:
            return JailConfigList(["-f", "root"])

    def _set_login_flags(self, value, **kwargs):
        if value is None:
            try:
                del self.data["login_flags"]
            except KeyError:
                pass
        else:
            if isinstance(value, list):
                self.data["login_flags"] = " ".join(value)
            elif isinstance(value, str):
                self.data["login_flags"] = value
            else:
                raise iocage.lib.errors.InvalidJailConfigValue(
                    property_name="login_flags",
                    logger=self.logger
                )

    def _get_host_hostuuid(self):
        try:
            return self.data["host_hostuuid"]
        except KeyError:
            return self["id"]

    def get_string(self, key):
        return self.stringify(self.__getitem__(key))

    def _skip_on_error(self, **kwargs):
        """
        A helper to resolve skip_on_error attribute
        """
        try:
            return kwargs["skip_on_error"] is True
        except AttributeError:
            return False

    def __getitem_user(self, key: str) -> typing.Any:

        # passthrough existing properties
        try:
            return self.__getattribute__(key)
        except AttributeError:
            pass

        is_special_property = self.special_properties.is_special_property(key)
        is_existing = key in self.data.keys()
        if (is_special_property and is_existing) is True:
            return self.special_properties.get_or_create(key)

        # data with mappings
        method_name = f"_get_{key}"
        if method_name in dict.__dir__(self):
            get_method = self.__getattribute__(method_name)
            return get_method()

        # plain data attribute
        if key in self.data.keys():
            return self.data[key]

        raise KeyError(f"User defined property not found: {key}")

    def __getitem__(self, key: str) -> typing.Any:

        try:
            return self.__getitem_user(key)
        except KeyError:
            pass

        raise KeyError(f"Item not found: {key}")

    def __delitem__(self, key: str) -> None:
        del self.data[key]

    def __setitem__(
        self,
        key: str,
        value: typing.Any,
        **kwargs
    ) -> None:

        parsed_value = iocage.lib.helpers.parse_user_input(value)

        if self.special_properties.is_special_property(key):
            special_property = self.special_properties.get_or_create(key)
            special_property.set(value)
            self.update_special_property(key)
            return

        setter_method_name = f"_set_{key}"
        if setter_method_name in object.__dir__(self):
            setter_method = self.__getattribute__(setter_method_name)
            setter_method(parsed_value, **kwargs)
            return

        self.data[key] = parsed_value

    def set(self, key: str, value: typing.Any, **kwargs) -> bool:
        """
        Set a JailConfig property

        Args:

            key:
                The jail config property name

            value:
                Value to set the property to

            **kwargs:
                Arguments from **kwargs are passed to setter functions

        Returns:

            bool: True if the JailConfig was changed
        """
        hash_before: typing.Any
        hash_after: typing.Any

        existed_before = key in self.user_data

        try:
            hash_before = str(self.__getitem_user(key)).__hash__()
        except Exception:
            hash_before = None

        self.__setitem__(key, value, **kwargs)

        exists_after = key in self.user_data

        try:
            hash_after = str(self.__getitem_user(key)).__hash__()
        except Exception:
            hash_after = None

        if existed_before != exists_after:
            return True

        return (hash_before != hash_after) is True

    @property
    def user_data(self) -> typing.Dict[str, typing.Any]:
        return self.data

    def __str__(self) -> str:
        return str(iocage.lib.helpers.to_json(self.data))

    def __dir__(self) -> list:

        properties = set()
        props = dict.__dir__(self)
        for prop in props:
            if not prop.startswith("_"):
                properties.add(prop)

        for key in self.data.keys():
            properties.add(key)

        return list(properties)

    @property
    def all_properties(self) -> list:
        return sorted(self.data.keys())

    def stringify(self, value: typing.Any):
        parsed_input = iocage.lib.helpers.parse_user_input(value)
        return iocage.lib.helpers.to_string(parsed_input)


class JailConfigList(list):

    def __str__(self) -> str:
        return " ".join(self)
