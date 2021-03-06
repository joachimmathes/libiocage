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
import os.path
import abc

import libzfs

import iocage.lib.Config
import iocage.lib.Config.Jail.Defaults
import iocage.lib.Config.Type.JSON
import iocage.lib.Config.Type.UCL
import iocage.lib.Config.Type.ZFS
import iocage.lib.Filter
import iocage.lib.Logger
import iocage.lib.Types
import iocage.lib.ZFS
import iocage.lib.helpers


class Resource(metaclass=abc.ABCMeta):
    """
    iocage resource

    An iocage resource is the representation of a jail, release or base release

    File Structure:

        <ZFSDataset>/root:

            This dataset contains the root filesystem of a jail or release.

            In case of a ZFS basejail resource it hosts a tree of child
            datasets that may be cloned into an existing target dataset.

        <ZFSDataset>/config.json:

            The resource configuration in JSON format

        <ZFSDataset>/config:

            The resource configuration in ucl format used by former versions
            of iocage

        <ZFSDataset>.properties:

            iocage legacy used to store resource configuration in ZFS
            properties on the resource dataset

    """

    CONFIG_TYPES = (
        "json",
        "ucl",
        "zfs",
        "auto"
    )

    DEFAULT_JSON_FILE = "config.json"
    DEFAULT_UCL_FILE = "config"

    _config_type: typing.Optional[int] = None
    _config_file: typing.Optional[str] = None
    _dataset: libzfs.ZFSDataset
    _dataset_name: str

    def __init__(
        self,
        dataset: typing.Optional[libzfs.ZFSDataset]=None,
        dataset_name: typing.Optional[str]=None,
        config_type: str="auto",  # auto, json, zfs, ucl
        config_file: typing.Optional[str]=None,  # 'config.json', 'config', etc
        logger: typing.Optional[iocage.lib.Logger.Logger]=None,
        zfs: typing.Optional[iocage.lib.ZFS.ZFS]=None
    ) -> None:

        self.logger = iocage.lib.helpers.init_logger(self, logger)
        self.zfs = iocage.lib.helpers.init_zfs(self, zfs)

        self._config_file = config_file
        self.config_type = config_type

        if dataset_name is not None:
            self.dataset_name = dataset_name
        elif dataset is not None:
            self.dataset = dataset

    @property
    def config_json(self) -> 'iocage.lib.Config.Type.JSON.ResourceConfigJSON':
        default = self.DEFAULT_JSON_FILE
        file = self._config_file if self._config_file is not None else default
        return iocage.lib.Config.Type.JSON.ResourceConfigJSON(
            file=file,
            resource=self,
            logger=self.logger
        )

    @property
    def config_ucl(self) -> 'iocage.lib.Config.Type.UCL.ResourceConfigUCL':
        default = self.DEFAULT_UCL_FILE
        file = self._config_file if self._config_file is not None else default
        return iocage.lib.Config.Type.UCL.ResourceConfigUCL(
            file=file,
            resource=self,
            logger=self.logger
        )

    @property
    def config_zfs(self) -> 'iocage.lib.Config.Type.ZFS.ResourceConfigZFS':
        return iocage.lib.Config.Type.ZFS.ResourceConfigZFS(
            resource=self,
            logger=self.logger
        )

    @abc.abstractmethod
    def destroy(self, force: bool=False) -> None:
        pass

    @property
    def pool(self) -> libzfs.ZFSPool:
        zpool: libzfs.ZFSPool = self.zfs.get_pool(self.dataset_name)
        return zpool

    @property
    def pool_name(self) -> str:
        return str(self.pool.name)

    @property
    def exists(self) -> bool:
        try:
            return os.path.isdir(self.dataset.mountpoint)
        except (AttributeError, libzfs.ZFSException):
            return False

    @property
    def _assigned_dataset_name(self) -> str:
        """
        Name of the jail's base ZFS dataset manually assigned to this resource
        """
        try:
            return str(self._dataset_name)
        except AttributeError:
            pass

        try:
            return str(self._dataset.name)
        except AttributeError:
            pass

        raise AttributeError("Could not determine dataset_name")

    @property
    def dataset_name(self) -> str:
        return self._assigned_dataset_name

    @dataset_name.setter
    def dataset_name(self, value: str) -> None:
        self._dataset_name = value

    @property
    def dataset(self) -> libzfs.ZFSDataset:
        try:
            return self._dataset
        except AttributeError:
            name = self.dataset_name
            dataset: libzfs.ZFSDataset = self.zfs.get_dataset(name)
            self._dataset = dataset
            return dataset

    @dataset.setter
    def dataset(self, value: libzfs.ZFSDataset) -> None:
        self._set_dataset(value)

    def _set_dataset(self, value: libzfs.ZFSDataset) -> None:
        try:
            del self._dataset_name
        except AttributeError:
            pass
        self._dataset = value

    @property
    def config_type(self) -> typing.Optional[str]:
        if self._config_type is None:
            return None
        elif self._config_type == self.CONFIG_TYPES.index("auto"):
            self._config_type = self._detect_config_type()
        return self.CONFIG_TYPES[self._config_type]

    @config_type.setter
    def config_type(self, value: typing.Optional[int]):
        if value is None:
            self._config_type = None
        else:
            self._config_type = self.CONFIG_TYPES.index(value)

    def _detect_config_type(self) -> int:

        if self.config_json.exists:
            return self.CONFIG_TYPES.index("json")

        if self.config_ucl.exists:
            return self.CONFIG_TYPES.index("ucl")

        if self.config_zfs.exists:
            return self.CONFIG_TYPES.index("zfs")

        return 0

    @property
    def config_file(self) -> typing.Optional[str]:
        """
        Relative path of the resource config file
        """
        if self._config_type is None:
            return None

        elif self._config_file is not None:
            return self._config_file

        elif self.config_type == "json":
            return self.DEFAULT_JSON_FILE

        elif self.config_type == "ucl":
            return self.DEFAULT_UCL_FILE

        return None

    @config_file.setter
    def config_file(self, value: str) -> None:
        self._config_file = value

    def create_resource(self) -> None:
        """
        Creates the dataset
        """
        self.dataset = self.zfs.create_dataset(self.dataset_name)
        os.chmod(self.dataset.mountpoint, 0o700)

    def get_dataset(self, name: str) -> libzfs.ZFSDataset:
        dataset_name = f"{self.dataset_name}/{name}"
        dataset: libzfs.ZFSDataset = self.zfs.get_dataset(dataset_name)
        return dataset

    def get_or_create_dataset(self, name: str, **kwargs) -> libzfs.ZFSDataset:
        """
        Get or create a child dataset

        Returns:

            libzfs.ZFSDataset:
                Existing or newly created ZFS Dataset
        """
        dataset_name = f"{self.dataset_name}/{name}"
        dataset: libzfs.ZFSDataset = self.zfs.get_or_create_dataset(
            dataset_name,
            **kwargs
        )
        return dataset

    def abspath(self, relative_path: str) -> str:
        return str(os.path.join(self.dataset.mountpoint, relative_path))

    def write_config(self, data: dict) -> None:
        self.config_handler.write(data)

    def read_config(self) -> typing.Dict[str, typing.Any]:
        o = self.config_handler.read()  # type: typing.Dict[str, typing.Any]
        return o

    @property
    def config_handler(self) -> 'iocage.lib.Config.Prototype.Prototype':
        handler = object.__getattribute__(self, f"config_{self.config_type}")
        return handler

    def get(self, key: str) -> typing.Any:
        try:
            return self.__getattribute__(key)
        except AttributeError:
            return None

    def getstring(self, key: str) -> str:
        """
        Returns the resource propertiey string or '-'

        Args:
            key (string):
                Name of the jail property to return
        """
        value = self.get(key)
        return str(iocage.lib.helpers.to_string(
            value,
            none="-"
        ))

    def save(self) -> None:
        raise NotImplementedError(
            "This needs to be implemented by the inheriting class"
        )


class DefaultResource(Resource):

    DEFAULT_JSON_FILE = "defaults.json"
    DEFAULT_UCL_FILE = "defaults"

    def __init__(
        self,
        dataset: typing.Optional[libzfs.ZFSDataset]=None,
        logger: typing.Optional[iocage.lib.Logger.Logger]=None,
        zfs: typing.Optional[iocage.lib.ZFS.ZFS]=None
    ) -> None:

        Resource.__init__(
            self,
            dataset=dataset,
            logger=logger,
            zfs=zfs
        )

        self.config = iocage.lib.Config.Jail.Defaults.JailConfigDefaults(
            logger=logger
        )

    def destroy(self, force: bool=False) -> None:
        raise NotImplementedError("destroy unimplemented for DefaultResource")

    def save(self) -> None:
        self.write_config(self.config.user_data)


class ListableResource(list, Resource):

    _filters: typing.Optional[iocage.lib.Filter.Terms] = None

    def __init__(
        self,
        dataset: typing.Optional[libzfs.ZFSDataset]=None,
        filters: typing.Optional[iocage.lib.Filter.Terms]=None,
        logger: typing.Optional[iocage.lib.Logger.Logger]=None,
        zfs: typing.Optional[iocage.lib.ZFS.ZFS]=None,
    ) -> None:

        list.__init__(self, [])

        Resource.__init__(
            self,
            dataset=dataset,
            logger=logger,
            zfs=zfs
        )

        self.filters = filters

    def destroy(self, force: bool=False) -> None:
        raise NotImplementedError("destroy unimplemented for ListableResource")

    def __iter__(
        self
    ) -> typing.Generator[Resource, None, None]:

        for child_dataset in self.dataset.children:

            name = self._get_asset_name_from_dataset(child_dataset)
            if self._filters is not None and \
               self._filters.match_key("name", name) is not True:
                # Skip all jails that do not even match the name
                continue

            # ToDo: Do not load jail if filters do not require to
            resource = self._get_resource_from_dataset(child_dataset)
            if self._filters is not None:
                if self._filters.match_resource(resource):
                    yield resource

    def __len__(self) -> int:
        return len(list(self.__iter__()))

    def _get_asset_name_from_dataset(
        self,
        dataset: libzfs.ZFSDataset
    ) -> str:
        """
        Returns the last fragment of a dataset's name

        Example:
            /iocage/jails/foo -> foo
        """

        return str(dataset.name.split("/").pop())

    def _get_resource_from_dataset(
        self,
        dataset: libzfs.ZFSDataset
    ) -> Resource:

        return self._create_resource_instance(dataset)

    @property
    def filters(self) -> typing.Optional[iocage.lib.Filter.Terms]:
        return self._filters

    @filters.setter
    def filters(
        self,
        value: typing.Iterable[typing.Union[iocage.lib.Filter.Term, str]]
    ):

        if isinstance(value, iocage.lib.Filter.Terms):
            self._filters = value
        else:
            self._filters = iocage.lib.Filter.Terms(value)

    @abc.abstractmethod
    def _create_resource_instance(
        self,
        dataset: libzfs.ZFSDataset,
        *args,
        **kwargs
    ) -> Resource:
        pass
