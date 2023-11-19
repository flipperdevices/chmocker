#!/usr/bin/env python3

import os
import tarfile
import logging
import argparse
from pathlib import Path
from dockerfile_parse import DockerfileParser

CHMOCKER_DIR_NAME = ".chmo"
CHMOCKER_DIR_PATH = Path.home() / CHMOCKER_DIR_NAME
CHMOCKER_BASE_IMAGES_DIR_NAME = "images"
CHMOCKER_BASE_IMAGES_DIR_PATH = CHMOCKER_DIR_PATH / Path(CHMOCKER_BASE_IMAGES_DIR_NAME)
CHMOCKER_MOUNT_IMAGES_DIR_NAME = "images_mount"
CHMOCKER_MOUNT_IMAGES_DIR_PATH = CHMOCKER_DIR_PATH / Path(
    CHMOCKER_MOUNT_IMAGES_DIR_NAME
)


class Chmoker:
    @staticmethod
    def parse_args():
        parser = argparse.ArgumentParser()
        parser.add_argument("action", choices=["build", "run"], help="Action to do")
        parser.add_argument(
            "command", help="Command to execute", nargs="?", default=None
        )
        return parser.parse_args()

    @staticmethod
    def check_root():
        if os.geteuid() != 0:
            raise Exception("This script must be runned as root!")

    def __init__(self):
        self.check_root()
        os.makedirs(CHMOCKER_DIR_PATH, exist_ok=True)
        os.makedirs(CHMOCKER_BASE_IMAGES_DIR_PATH, exist_ok=True)
        os.makedirs(CHMOCKER_MOUNT_IMAGES_DIR_PATH, exist_ok=True)
        logger = logging.getLogger()
        logger.setLevel(logging.INFO)
        self.args = self.parse_args()
        self.baseimage: str = None

    def parse_instr(self, instr):
        command = instr["instruction"]
        if command == "COMMENT":
            return
        if command == "FROM":
            return
        self.exec_in_chroot(f"sh -c 'echo {command}'")

    def unpack_image(self):
        image_orig_path = CHMOCKER_BASE_IMAGES_DIR_PATH / Path(f"{self.baseimage}.tar")
        image_mount_path = CHMOCKER_MOUNT_IMAGES_DIR_PATH / Path(self.baseimage)
        logging.info(f"Unpacking base image {image_orig_path} to {image_mount_path}")
        if not image_orig_path.exists():
            raise Exception(f"Image {image_orig_path} not found!")
        if image_mount_path.exists():
            os.remove(image_mount_path)
        tar = tarfile.open(image_orig_path)
        tar.extractall(path=image_mount_path)
        tar.close()

    def prepare_chroot(self):
        image_mount_path = CHMOCKER_MOUNT_IMAGES_DIR_PATH / Path(self.baseimage)
        # self.unpack_image()
        logging.info(f"Addind hardlink to mDNSResponder to {self.baseimage}")
        image_mount_dns_responder_path = image_mount_path / Path(
            "var/run/mDNSResponder"
        )
        if image_mount_dns_responder_path.exists():
            os.remove(image_mount_dns_responder_path)
        os.link(Path("/var/run/mDNSResponder"), image_mount_dns_responder_path)
        logging.info(f"Mounting devfs to {self.baseimage}")
        self.exec_in_chroot("mount -t devfs devfs /dev")

    def exec_in_chroot(self, command):
        image_mount_path = CHMOCKER_MOUNT_IMAGES_DIR_PATH / Path(self.baseimage)
        env_vars = [
            "HOME=/root",
            'TERM="$TERM"',
            "PS1='\\u:\w\$ '",
            'PATH="$PATH"',
            "TMPDIR=/tmp",
            "HOMEBREW_CELLAR=/opt/homebrew/Cellar",
            "HOMEBREW_PREFIX=/opt/homebrew",
            "HOMEBREW_REPOSITORY=/opt/homebrew",
        ]
        env_vars_str = " ".join(env_vars)
        os.system(f"chroot {image_mount_path} env -i {env_vars_str} {command}")

    def destroy_chroot(self):
        logging.info(f"Destroying chroot of {self.baseimage}")
        image_mount_path = CHMOCKER_MOUNT_IMAGES_DIR_PATH / Path(self.baseimage)
        image_mount_dns_responder_path = image_mount_path / Path(
            "var/run/mDNSResponder"
        )
        if image_mount_dns_responder_path.exists():
            logging.info(f"Removing hardlink to mDNSResponder from {self.baseimage}")
            os.remove(image_mount_dns_responder_path)
        logging.info(f"Umounting devfs to {self.baseimage}")
        self.exec_in_chroot("umount /dev")

    def build(self):
        logging.info("Building image..")
        dfp = DockerfileParser()
        self.baseimage = dfp.baseimage
        self.prepare_chroot()
        [self.parse_instr(x) for x in dfp.structure]
        if self.args.command:
            self.exec_in_chroot(self.args.command)
        self.destroy_chroot()

    def run(self):
        if self.args.action == "build":
            self.build()
        if self.args.action == "run":
            raise Exception("Not implemented")


if __name__ == "__main__":
    chmo = Chmoker()
    chmo.run()
