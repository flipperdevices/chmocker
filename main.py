#!/usr/bin/env python3

import os
import glob
import tarfile
import logging
import argparse
import shutil
import subprocess
import validators
from pathlib import Path
from urllib.request import urlretrieve
from dockerfile_parse import DockerfileParser

CHMOCKER_DIR_NAME = ".chmo"
CHMOCKER_DIR_PATH = Path.home() / CHMOCKER_DIR_NAME
CHMOCKER_BASE_IMAGES_DIR_NAME = "images"
CHMOCKER_BASE_IMAGES_DIR_PATH = CHMOCKER_DIR_PATH / Path(CHMOCKER_BASE_IMAGES_DIR_NAME)
CHMOCKER_MOUNT_IMAGES_DIR_NAME = "images_mount"
CHMOCKER_MOUNT_IMAGES_DIR_PATH = CHMOCKER_DIR_PATH / Path(
    CHMOCKER_MOUNT_IMAGES_DIR_NAME
)

CHMOCKER_SYSTEM_IMAGE_PATHS = (
    "/bin",
    "/sbin",
    "/usr/lib",
    "/usr/bin",
    "/usr/sbin",
    "/usr/share",
    "/usr/libexec",
    "/etc/pam.d",
    "/etc/ssl",
    "/etc/sudoers",
    "/var/db/timezone",
    "/System/Library/CoreServices/SystemVersion.plist",
    "/System/Library/CoreServices/SystemVersionCompat.plist",
    "/System/Library/Frameworks",
    "/System/Library/Perl",
    "/Library/Developer/CommandLineTools",
    "/usr/libexec/rosetta",
    "/Library/Apple/usr/libexec/oah",
)


class Chmoker:
    @staticmethod
    def parse_args():
        parser = argparse.ArgumentParser()
        action_subparsers = parser.add_subparsers(dest="action", help="Action to do")
        action_subparsers.required = True

        image_parser = action_subparsers.add_parser("image")
        image_subparsers = image_parser.add_subparsers(
            dest="image_action", help="Action to do with image"
        )
        image_subparsers.required = True
        image_create_parser = image_subparsers.add_parser("create")
        image_create_parser.add_argument("-t", "--tag", help="Image tag", required=True)
        image_create_parser.add_argument(
            "--recreate",
            dest="image_recreate",
            action="store_true",
            help="Force recreate image",
            default=False,
        )
        image_create_parser.add_argument(
            "--no-tar",
            dest="image_no_tar",
            action="store_true",
            help="Do not produce tar archive",
            default=False,
        )
        image_create_parser.add_argument(
            "--no-brew",
            dest="image_no_brew",
            action="store_true",
            help="Do not install Brew into the image",
            default=False,
        )
        image_ls_parser = image_subparsers.add_parser("ls")

        build_parser = action_subparsers.add_parser("build")
        build_parser.add_argument("-t", "--tag", help="Image tag", required=True)
        build_parser.add_argument(
            "--refresh",
            dest="build_force_refresh",
            action="store_true",
            help="Force refresh already unpacked image",
            default=False,
        )

        run_parser = action_subparsers.add_parser("run")
        run_parser.add_argument("tag", help="Image tag")
        run_parser.add_argument(
            "--rm",
            dest="run_remove_after",
            action="store_true",
            help="Remove container after run",
            default=False,
        )
        run_parser.add_argument(
            "--it",
            dest="run_interactive",
            action="store_true",
            help="Run command in interactive mode",
            default=False,
        )
        run_parser.add_argument(
            "--refresh",
            dest="run_force_refresh",
            action="store_true",
            help="Force refresh already unpacked image",
            default=False,
        )
        run_parser.add_argument(
            "command", help="Command to execute", nargs="?", default=None
        )
        return parser.parse_args()

    @staticmethod
    def check_root():
        if os.geteuid() != 0:
            raise Exception("This script must be runned as root!")

    @staticmethod
    def copy_with_metadata(source_path, target_path):
        os.system(f"cp -af {source_path} {target_path}")  # TODO: replace to Popen

    @staticmethod
    def get_size_str(path):
        return subprocess.check_output(["du", "-sh", path]).split()[0].decode("utf-8")

    @staticmethod
    def create_tar_archive(tar_path, source_path):
        logging.info(f"Creating tar archive {tar_path}..")
        tar = tarfile.open(tar_path, "w")
        for root_dir_item in os.listdir(source_path):
            root_dir_item_path = source_path / Path(root_dir_item)
            tar.add(root_dir_item_path, root_dir_item)
        tar.close()
        logging.info(f"Image tar size {self.get_size_str(image_tar_path)}")

    def __init__(self):
        self.check_root()
        os.makedirs(CHMOCKER_DIR_PATH, exist_ok=True)
        os.makedirs(CHMOCKER_BASE_IMAGES_DIR_PATH, exist_ok=True)
        os.makedirs(CHMOCKER_MOUNT_IMAGES_DIR_PATH, exist_ok=True)
        logger = logging.getLogger()
        logger.setLevel(logging.INFO)
        self.args = self.parse_args()

    def parse_add_instr(self, image_tag, command_value):
        image_mount_path = CHMOCKER_MOUNT_IMAGES_DIR_PATH / Path(image_tag)
        src, dst = command_value.split()
        target_path = image_mount_path / Path(dst.strip("/"))
        os.makedirs(target_path, exist_ok=True)
        if validators.url(src):
            filename = Path(src).name
            urlretrieve(src, target_path / Path(filename))
        else:
            src_path = Path(src)
            if not src_path.exists():
                raise Exception(f"No such file or directory {src})")
            if os.path.isdir(src_path):
                target_dir_path = target_path / Path(src_path.name)
                shutil.copytree(src_path, f"{target_dir_path}/", dirs_exist_ok=True)
            elif os.path.isfile(src_path):
                if tarfile.is_tarfile(src_path):
                    tar = tarfile.open(src_path)
                    tar.extractall(path=target_path)
                    tar.close()
                else:
                    shutil.copy2(src_path, f"{target_path}/")
            else:
                raise Exception(f"Failed to parse {src})")

    def parse_instr(self, image_tag, instr):
        command = instr["instruction"]
        if command == "COMMENT":
            return
        if command == "FROM":
            return  # TODO: implement
        full_line = instr["content"].replace("\n", "")
        command_value = instr["value"]
        print(full_line)
        if command == "RUN":
            self.exec_in_chroot(image_tag, command_value)
        elif command == "ADD":
            self.parse_add_instr(image_tag, command_value)

    def unpack_image(self, image_tag):
        image_orig_path = CHMOCKER_BASE_IMAGES_DIR_PATH / Path(f"{image_tag}.tar")
        image_mount_path = CHMOCKER_MOUNT_IMAGES_DIR_PATH / Path(image_tag)
        logging.info(f"Unpacking base image {image_orig_path} to {image_mount_path}")
        if not image_orig_path.exists():
            raise Exception(f"Image {image_orig_path} not found!")
        if image_mount_path.exists():
            os.remove(image_mount_path)
        tar = tarfile.open(image_orig_path)
        tar.extractall(path=image_mount_path)
        tar.close()

    def prepare_chroot(self, image_tag, force_refresh=False):
        image_mount_path = CHMOCKER_MOUNT_IMAGES_DIR_PATH / Path(image_tag)
        if not image_mount_path.exists() or force_refresh:
            self.unpack_image(image_tag)
        logging.info(f"Addind hardlink to mDNSResponder to {image_tag}")
        image_mount_dns_responder_path = image_mount_path / Path(
            "var/run/mDNSResponder"
        )
        if image_mount_dns_responder_path.exists():
            os.remove(image_mount_dns_responder_path)
        os.link(Path("/var/run/mDNSResponder"), image_mount_dns_responder_path)
        logging.info(f"Mounting devfs to {image_tag}")
        self.exec_in_chroot(image_tag, "mount -t devfs devfs /dev")

    def exec_in_chroot(self, image_tag, command, run_interactive=False):
        image_mount_path = CHMOCKER_MOUNT_IMAGES_DIR_PATH / Path(image_tag)
        env_vars = [
            "HOME=/",
            'TERM="$TERM"',
            "PS1='\\u:\w\$ '",
            'PATH="/opt/homebrew/bin:/opt/homebrew/sbin${PATH+:$PATH}"',
            "TMPDIR=/tmp",
            "HOMEBREW_CELLAR=/opt/homebrew/Cellar",
            "HOMEBREW_PREFIX=/opt/homebrew",
            "HOMEBREW_REPOSITORY=/opt/homebrew",
            "NONINTERACTIVE=1",
        ]
        env_vars_str = " ".join(env_vars)
        status = os.system(
            f"chroot {image_mount_path} env -i {env_vars_str} {command}"
        )  # TODO: interactive cond
        exit_code = os.waitstatus_to_exitcode(status)
        if exit_code != 0 and not run_interactive:
            raise Exception(f"Command '{command}' exited with code {exit_code}")

    def destroy_chroot(self, image_tag):
        logging.info(f"Destroying chroot of {image_tag}")
        image_mount_path = CHMOCKER_MOUNT_IMAGES_DIR_PATH / Path(image_tag)
        image_mount_dns_responder_path = image_mount_path / Path(
            "var/run/mDNSResponder"
        )
        if image_mount_dns_responder_path.exists():
            logging.info(f"Removing hardlink to mDNSResponder from {image_tag}")
            os.remove(image_mount_dns_responder_path)
        logging.info(f"Umounting devfs to {image_tag}")
        self.exec_in_chroot(image_tag, "umount /dev")

    def build(self):
        logging.info("Building image..")
        dfp = DockerfileParser()
        image_tag = dfp.baseimage
        self.prepare_chroot(image_tag, self.args.build_force_refresh)
        try:
            [self.parse_instr(image_tag, x) for x in dfp.structure]
        finally:
            self.destroy_chroot(image_tag)

    def copy_dyld_libs_to_image(self, image_mount_path):
        lib_target_dir = image_mount_path / Path("System/Library/dyld")
        os.makedirs(lib_target_dir, exist_ok=True)
        for lib in glob.glob(
            "/System/Volumes/Preboot/Cryptexes/OS/System/Library/dyld/dyld_shared_cache_*"
        ):
            logging.info(f"Copying {lib} to {lib_target_dir}/..")
            self.copy_with_metadata(lib, f"{lib_target_dir}/")

    def copy_system_to_image(self, image_mount_path):
        for path in CHMOCKER_SYSTEM_IMAGE_PATHS:
            target_path = image_mount_path / Path(
                path.strip("/")
            )  # removing leading slash
            target_dir = target_path.parents[0]
            logging.info(f"Copying {path} to {target_dir}/..")
            os.makedirs(target_dir, exist_ok=True)
            self.copy_with_metadata(path, f"{target_dir}/")

    def create_system_stuff(self, image_mount_path):
        os.makedirs(image_mount_path / Path("var/run"), exist_ok=True)
        os.makedirs(image_mount_path / Path("dev"), exist_ok=True)
        os.makedirs(image_mount_path / Path("private/tmp"), exist_ok=True)
        tmp_dir_path = image_mount_path / Path("tmp")
        if tmp_dir_path.exists():
            os.remove(tmp_dir_path)
        os.symlink("/private/tmp", tmp_dir_path)
        docker_env_path = image_mount_path / Path(".dockerenv")
        docker_env_path.touch()

    def create_system_image(self):
        image_mount_path = CHMOCKER_MOUNT_IMAGES_DIR_PATH / Path(self.args.tag)
        if image_mount_path.exists():
            if not self.args.image_recreate:
                logging.warning(
                    f"Image {self.args.tag} is already created, skipping.. Use '--recreate' flag to recreate"
                )
                return
        logging.info(f"Creating image {self.args.tag}..")
        image_tar_path = CHMOCKER_BASE_IMAGES_DIR_PATH / Path(f"{self.args.tag}.tar")
        self.copy_dyld_libs_to_image(image_mount_path)
        self.copy_system_to_image(image_mount_path)
        self.create_system_stuff(image_mount_path)
        if not self.args.image_no_brew:
            self.install_brew_into_image(image_mount_path)
        if not self.args.image_no_tar:
            self.create_tar_archive(image_tar_path, image_mount_path)

    def install_brew_into_image(self, image_mount_path):
        logging.info(f"Installing brew into {self.args.tag}")
        brew_install_cmd = 'bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"'
        self.prepare_chroot(self.args.tag)
        self.exec_in_chroot(self.args.tag, brew_install_cmd)
        self.destroy_chroot(self.args.tag)

    def image_ls(self):
        images_dir_tar_items = sorted(os.listdir(CHMOCKER_BASE_IMAGES_DIR_PATH))
        images_dir_mounted_items = sorted(os.listdir(CHMOCKER_MOUNT_IMAGES_DIR_PATH))
        print("Images (as .tar):")
        for n, item in enumerate(images_dir_tar_items):
            print(n + 1, item)
        print()
        print("Images (mounted):")
        for n, item in enumerate(images_dir_mounted_items):
            print(n + 1, item)

    def image(self):
        if self.args.image_action == "create":
            self.create_system_image()
        elif self.args.image_action == "ls":
            self.image_ls()

    def run(self):
        self.prepare_chroot(self.args.tag, self.args.run_force_refresh)
        self.exec_in_chroot(self.args.tag, self.args.command, self.args.run_interactive)
        self.destroy_chroot(self.args.tag)
        if self.args.run_remove_after:
            pass

    def main(self):
        if self.args.action == "build":
            self.build()
        elif self.args.action == "image":
            self.image()
        elif self.args.action == "run":
            self.run()


if __name__ == "__main__":
    chmo = Chmoker()
    chmo.main()
