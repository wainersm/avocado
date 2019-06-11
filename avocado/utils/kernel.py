# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 2 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.
#
# See LICENSE for more details.
#
# Copyright: Red Hat Inc. 2014
# Author: Ruda Moura <rmoura@redhat.com>
# Author: Santhosh G <santhog4@linux.vnet.ibm.com>

import abc
import os
import shutil
import logging
import tempfile
from distutils.version import LooseVersion  # pylint: disable=E0611

from . import asset, archive, build, distro, process

log = logging.getLogger('avocado.test')


class KernelBuild:

    """
    Build the Linux Kernel from official tarballs.
    """

    URL = 'https://www.kernel.org/pub/linux/kernel/v{major}.x/'
    SOURCE = 'linux-{version}.tar.gz'

    def __init__(self, version, config_path=None, work_dir=None,
                 data_dirs=None):
        """
        Creates an instance of :class:`KernelBuild`.

        :param version: kernel version ("3.19.8").
        :param config_path: path to config file.
        :param work_dir: work directory.
        :param data_dirs: list of directories to keep the downloaded kernel
        :return: None.
        """
        self.version = version
        self.config_path = config_path
        self.distro = distro.detect()
        if work_dir is None:
            work_dir = tempfile.mkdtemp(prefix='avocado_' + __name__)
        self.work_dir = work_dir
        if data_dirs is not None:
            self.data_dirs = data_dirs
        else:
            self.data_dirs = [self.work_dir]
        self.build_dir = os.path.join(self.work_dir, 'build')
        if not os.path.isdir(self.build_dir):
            os.makedirs(self.build_dir)

    def __repr__(self):
        return "KernelBuild('%s, %s, %s')" % (self.version,
                                              self.config_path,
                                              self.work_dir)

    def _build_kernel_url(self, base_url=None):
        kernel_file = self.SOURCE.format(version=self.version)
        if base_url is None:
            base_url = self.URL.format(major=self.version.split('.', 1)[0])
        return base_url + kernel_file

    def download(self, url=None):
        """
        Download kernel source.

        :param url: override the url from where to fetch the kernel
                    source tarball
        :type url: str or None
        """
        full_url = self._build_kernel_url(base_url=url)
        self.asset_path = asset.Asset(full_url, asset_hash=None,
                                      algorithm=None, locations=None,
                                      cache_dirs=self.data_dirs).fetch()

    def uncompress(self):
        """
        Uncompress kernel source.
        """
        log.info("Uncompressing tarball")
        archive.extract(self.asset_path, self.work_dir)

    def configure(self):
        """
        Configure/prepare kernel source to build.
        """
        self.linux_dir = os.path.join(self.work_dir, 'linux-%s' % self.version)
        build.make(self.linux_dir, extra_args='-C %s mrproper' %
                   self.linux_dir)
        if self.config_path is not None:
            dotconfig = os.path.join(self.linux_dir, '.config')
            shutil.copy(self.config_path, dotconfig)

    def build(self, binary_package=False):
        """
        Build kernel from source.

        :param binary_package: when True, the appropriate
                                  platform package is built
                                  for install() to use
        :type binary_pacakge: bool
        """
        log.info("Starting build the kernel")
        build_output_format = ""
        if binary_package is True:
            if self.distro.name == "Ubuntu":
                build_output_format = "deb-pkg"
        if self.config_path is None:
            build.make(self.linux_dir, extra_args='-C %s defconfig' %
                       self.linux_dir)
        else:
            build.make(self.linux_dir, extra_args='-C %s olddefconfig' %
                       self.linux_dir)
        build.make(self.linux_dir, extra_args='-C %s %s' %
                   (self.linux_dir, build_output_format))

    def install(self):
        """
        Install built kernel.
        """
        log.info("Starting kernel install")
        if self.distro.name == "Ubuntu":
            process.run('dpkg -i %s/*.deb' %
                        self.work_dir, shell=True, sudo=True)
        else:
            log.info("Skipping kernel install")

    def __del__(self):
        shutil.rmtree(self.work_dir)


def check_version(version):
    """
    This utility function compares the current kernel version with
    the version parameter and gives assertion error if the version
    parameter is greater.

    :type version: string
    :param version: version to be compared with current kernel version
    """
    assert LooseVersion(os.uname()[2]) > LooseVersion(version), "Old kernel"

class KernelProviderBase(abc.ABC):

    def get(self, version, arch=None, checksum=None,
        algorithm=None, cache_dir=None):

        if cache_dir is None:
            _cache_dir = tempfile.gettempdir()

        if arch:
            _arch = arch
        else:
            _arch = os.uname()[4]

        return self.get_impl(version, _arch, _cache_dir, checksum,
                             algorithm)

    @abc.abstractmethod
    def get_impl(self, version, arch, cache_dir, checksum, algorithm):
        pass

    @staticmethod
    def get_providers():
        return set(_ for _ in globals().values()
            if (isinstance(_, type) and
                issubclass(_, KernelProviderBase) and
                hasattr(_, 'name')))

class FedoraKernelProvider(KernelProviderBase):

    name = 'Fedora'
    edition = 'Everything'

    def get_impl(self, version, arch, cache_dir, checksum, algorithm):
        base_url = 'https://download.fedoraproject.org/pub/fedora/linux/releases/{version}/{edition}/{arch}/os/images/pxeboot'
        kernel_base_url = base_url + '/vmlinuz'
        initrd_base_url = base_url + '/initrd.img'

        if arch in ('ppc64', 'ppc64le', 's390x'):
            base_url = 'https://download.fedoraproject.org/pub/fedora-secondary/releases/{version}/{edition}/{arch}/os/images'
            kernel_base_url = base_url + '/kernel.img'
            initrd_base_url = base_url + '/initrd.img'

        kernel_url = kernel_base_url.format(version=version, arch=arch,
                                            edition=self.edition)
        initrd_url = initrd_base_url.format(version=version, arch=arch,
                                            edition=self.edition)

        initrd_path = asset.Asset(name="initrd-%s-%s-%s" % (self.name, version,
                                                            arch),
                                  asset_hash=checksum,
                                  algorithm=algorithm,
                                  locations=[initrd_url],
                                  cache_dirs=[cache_dir],
                                  expire=None).fetch()

        kernel_path = asset.Asset(name="vmlinuz-%s-%s-%s" % (self.name, version,
                                                             arch),
                                  asset_hash=checksum,
                                  algorithm=algorithm,
                                  locations=[kernel_url],
                                  cache_dirs=[cache_dir],
                                  expire=None).fetch()
        return Kernel(kernel_path, checksum, Initrd(initrd_path, checksum))

class Kernel:

    def __init__(self, path, checksum, initrd=None):
        self.path = path
        self.checksum = checksum
        self.initrd = initrd

class Initrd:

    def __init__(self, path, checksum):
        self.path = path
        self.checksum = checksum

def get(name=None, version=None, build=None, arch=None, checksum=None,
        algorithm=None, cache_dir=None, snapshot_dir=None):
    provider = [p  for p in list_providers() if p.name == name]
    print(provider)

def list_providers():
    return KernelProviderBase.get_providers()
