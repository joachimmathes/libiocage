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
import grp
import os
import pwd
import typing

import libzfs

import iocage.lib.events
import iocage.lib.helpers


class Storage:

    def __init__(
        self,
        jail: 'iocage.lib.Jail.JailGenerator',
        zfs: typing.Optional['iocage.lib.ZFS.ZFS']=None,
        safe_mode: bool=True,
        logger: typing.Optional['iocage.lib.Logger.Logger']=None
    ) -> None:

        self.logger = iocage.lib.helpers.init_logger(self, logger)
        self.zfs = iocage.lib.helpers.init_zfs(self, zfs)
        self.jail = jail

        # safe-mody only attaches zfs datasets to jails that were tagged with
        # jailed=on already exist
        self.safe_mode = safe_mode

    def clone_release(
        self,
        release: 'iocage.lib.Release.ReleaseGenerator'
    ) -> None:

        self.clone_zfs_dataset(
            release.root_dataset_name,
            self.jail.root_dataset_name
        )
        jail_name = self.jail.humanreadable_name
        self.logger.verbose(
            f"Cloned release '{release.name}' to {jail_name}",
            jail=self.jail
        )

    def rename(
        self,
        new_name: str
    ) -> typing.Generator['iocage.lib.events.IocageEvent', None, None]:

        for event in self._rename_dataset(new_name):
            yield event

        for event in self._rename_snapshot(new_name):
            yield event

    def _rename_dataset(
        self,
        new_name: str
    ) -> typing.Generator['iocage.lib.events.IocageEvent', None, None]:

        current_dataset_name = self.jail.dataset.name
        renameDatasetEvent = iocage.lib.events.ZFSDatasetRename(
            dataset=self.jail.dataset
        )
        yield renameDatasetEvent.begin()

        try:
            new_dataset_name = "/".join([
                self.jail.host.datasets.jails.name,
                new_name
            ])
            self.jail.dataset.rename(new_dataset_name)
            self.jail.dataset_name = new_dataset_name
            self.logger.verbose(
                f"Dataset {current_dataset_name} renamed to {new_dataset_name}"
            )
            yield renameDatasetEvent.end()
        except BaseException as e:
            yield renameDatasetEvent.fail(e)

    def _rename_snapshot(
        self,
        new_name: str
    ) -> typing.Generator['iocage.lib.events.IocageEvent', None, None]:

        root_dataset_properties = self.jail.root_dataset.properties

        if "origin" not in root_dataset_properties:
            return

        snapshot = self.zfs.get_snapshot(
            root_dataset_properties["origin"].value
        )

        renameSnapshotEvent = iocage.lib.events.ZFSSnapshotRename(
            snapshot=self.jail.dataset
        )
        yield renameSnapshotEvent.begin()

        try:
            new_snapshot_name = f"{snapshot.parent.name}@{new_name}"
            snapshot.rename(new_snapshot_name)
            yield renameSnapshotEvent.end()
        except BaseException as e:
            yield renameSnapshotEvent.fail(e)

    def clone_zfs_dataset(
        self,
        source: str,
        target: str
    ) -> None:

        snapshot_name = f"{source}@{self.jail.name}"

        # delete target dataset if it already exists
        try:
            existing_dataset = self.zfs.get_dataset(target)
        except libzfs.ZFSException:
            pass
        else:
            self.logger.verbose(
                f"Deleting existing dataset {target}",
                jail=self.jail
            )
            if existing_dataset.mountpoint is not None:
                existing_dataset.umount()
            existing_dataset.delete()
            del existing_dataset

        # delete existing snapshot if existing
        existing_snapshot = None
        try:
            existing_snapshot = self.zfs.get_snapshot(snapshot_name)
        except libzfs.ZFSException:
            pass
        else:
            self.logger.verbose(
                f"Deleting existing snapshot {snapshot_name}",
                jail=self.jail
            )
            existing_snapshot.delete()

        # snapshot release
        self.zfs.get_dataset(source).snapshot(snapshot_name)
        snapshot = self.zfs.get_snapshot(snapshot_name)

        # clone snapshot
        try:
            self.logger.verbose(
                f"Cloning snapshot {snapshot_name} to {target}",
                jail=self.jail
            )
            snapshot.clone(target)
        except libzfs.ZFSException:
            parent = "/".join(target.split("/")[:-1])
            self.logger.debug(
                "Cloning was unsuccessful - "
                f"trying to create the parent dataset '{parent}' first",
                jail=self.jail
            )
            self.zfs.create_dataset(parent)
            snapshot.clone(target)

        target_dataset = self.zfs.get_dataset(target)
        target_dataset.mount()
        self.logger.verbose(
            f"Successfully cloned {source} to {target}",
            jail=self.jail
        )

    def create_jail_mountpoint(self, basedir: str) -> None:
        basedir = f"{self.jail.root_dataset.mountpoint}/{basedir}"
        if not os.path.isdir(basedir):
            self.logger.verbose(f"Creating mountpoint {basedir}")
            os.makedirs(basedir)

    def _mount_procfs(self) -> None:
        try:
            if self.jail.config["mount_procfs"] is True:
                iocage.lib.helpers.exec([
                    "mount"
                    "-t",
                    "procfs"
                    "proc"
                    f"{self.jail.root_dataset.mountpoint}/proc"
                ])
        except KeyError:
            raise iocage.lib.errors.MountFailed(
                "procfs",
                logger=self.logger
            )

    # ToDo: Remove unused function?
    def _mount_linprocfs(self):
        try:
            if not self.jail.config["mount_linprocfs"]:
                return
        except KeyError:
            pass

        linproc_path = self._jail_mkdirp("/compat/linux/proc")

        try:
            if self.jail.config["mount_procfs"] is True:
                iocage.lib.helpers.exec([
                    "mount"
                    "-t",
                    "linprocfs",
                    "linproc",
                    linproc_path
                ])
        except KeyError:
            raise iocage.lib.errors.MountFailed("linprocfs")

    def _jail_mkdirp(
        self,
        directory: str,
        permissions=0o775,
        user: str="root",
        group: str="wheel"
    ) -> str:

        uid = pwd.getpwnam(user).pw_uid
        gid = grp.getgrnam(group).gr_gid
        folder = f"{self.jail.root_dataset.mountpoint}{directory}"
        if not os.path.isdir(folder):
            os.makedirs(folder, permissions)
            os.chown(folder, uid, gid, follow_symlinks=False)
        return str(os.path.abspath(folder))
