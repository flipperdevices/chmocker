#!/usr/bin/env python3

import os
import tarfile
import logging
import argparse
from pathlib import Path
from dockerfile_parse import DockerfileParser

CHMOCKER_DIR_NAME = ".chmo"
CHMOCKER_DIR_PATH = Path.home() / CHMOCKER_DIR_NAME
CHMOCKER_BASE_IMAGES_DIR_NAME = "images_base"
CHMOCKER_BASE_IMAGES_DIR_PATH = CHMOCKER_DIR_PATH / Path(CHMOCKER_BASE_IMAGES_DIR_NAME)
CHMOCKER_UNPACKED_IMAGES_DIR_NAME = "images_unpack"
CHMOCKER_UNPACKED_IMAGES_DIR_PATH = CHMOCKER_DIR_PATH / Path(
    CHMOCKER_UNPACKED_IMAGES_DIR_NAME
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
        logging.info(f"Unpacking base image {self.baseimage}.tar")
        image_tar_path = CHMOCKER_BASE_IMAGES_DIR_PATH / Path(f"{self.baseimage}.tar")
        if not image_tar_path.exists():
            raise Exception(f"Image {image_tar_path} not found!")
        tar = tarfile.open(image_tar_path)
        tar.extractall(path=CHMOCKER_UNPACKED_IMAGES_DIR_PATH)
        tar.close()

    def prepare_chroot(self):
        logging.info(f"Preparing base image {self.baseimage}")
        image_unpacked_path = CHMOCKER_UNPACKED_IMAGES_DIR_PATH / Path(self.baseimage)
        if not image_unpacked_path.exists():
            self.unpack_image()
        logging.info(f"Addind hardlink to mDNSResponder to {self.baseimage}")
        image_unpacked_dns_responder_path = image_unpacked_path / Path(
            "var/run/mDNSResponder"
        )
        if image_unpacked_dns_responder_path.exists():
            os.remove(image_unpacked_dns_responder_path)
        os.link(Path("/var/run/mDNSResponder"), image_unpacked_dns_responder_path)

    def exec_in_chroot(self, command):
        image_unpacked_path = CHMOCKER_UNPACKED_IMAGES_DIR_PATH / Path(self.baseimage)
        os.system(f"chroot {image_unpacked_path} {command}")

    def destroy_chroot(self):
        logging.info(f"Destroying chroot of {self.baseimage}")
        image_unpacked_path = CHMOCKER_UNPACKED_IMAGES_DIR_PATH / Path(self.baseimage)
        image_unpacked_dns_responder_path = image_unpacked_path / Path(
            "var/run/mDNSResponder"
        )
        if image_unpacked_dns_responder_path.exists():
            logging.info(f"Removing hardlink to mDNSResponder from {self.baseimage}")
            os.remove(image_unpacked_dns_responder_path)

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
