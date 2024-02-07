#!/usr/bin/env python3
import subprocess
import argparse
import tarfile
import logging
import hashlib
import shutil
import json
import glob
import os
from urllib.request import urlretrieve
from pathlib import Path
from typing import TextIO

import validators
from dockerfile_parse import parser, DockerfileParser
from termcolor import colored

CHMOCKER_DIR_NAME = ".chmo"
CHMOCKER_DIR_PATH = Path.home() / CHMOCKER_DIR_NAME
CHMOCKER_BASE_IMAGES_DIR_NAME = "images"
CHMOCKER_BASE_IMAGES_DIR_PATH = CHMOCKER_DIR_PATH / Path(CHMOCKER_BASE_IMAGES_DIR_NAME)
CHMOCKER_MOUNT_IMAGES_DIR_NAME = "images_mount"
CHMOCKER_MOUNT_IMAGES_DIR_PATH = CHMOCKER_DIR_PATH / Path(CHMOCKER_MOUNT_IMAGES_DIR_NAME)
CHMOKER_INDEX_FILE_NAME = "index.json"
CHMOKER_INDEX_FILE_PATH = CHMOCKER_DIR_PATH / Path(CHMOKER_INDEX_FILE_NAME)

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
        image_subparsers = image_parser.add_subparsers(dest="image_action", help="Action to do with image")
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
            help="Do not produce tar archive and do not remove unpacked",
            default=False,
        )
        image_create_parser.add_argument(
            "--no-remove",
            dest="image_no_remove",
            action="store_true",
            help="Do not remove unpacked image",
            default=False,
        )
        image_create_parser.add_argument(
            "--no-brew",
            dest="image_no_brew",
            action="store_true",
            help="Do not install Brew into the image",
            default=False,
        )

        build_parser = action_subparsers.add_parser("build")
        build_parser.add_argument("-t", "--tag", help="Image tag", required=True)
        build_parser.add_argument(
            "--refresh",
            dest="build_force_refresh",
            action="store_true",
            help="Force refresh already unpacked image",
            default=False,
        )
        build_parser.add_argument(
            "--no-tar",
            dest="build_no_tar",
            action="store_true",
            help="Do not produce tar archive",
            default=False,
        )
        build_parser.add_argument(
            "--no-remove",
            dest="build_no_remove",
            action="store_true",
            help="Do not remove unpacked image",
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
            "-e",
            dest="run_extra_envs",
            action="append",
            help="Extra container environment variables",
            default=[],
        )
        run_parser.add_argument("command", help="Command to execute", nargs="?", default=None)
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
    def remove_recursive_force(path):
        logging.info(f"Removing {path}..")
        if os.path.islink(path):
            os.unlink(path)
        elif os.path.isfile(path):
            os.remove(path)
        else:
            shutil.rmtree(path)

    def __init__(self):
        self.check_root()
        os.makedirs(CHMOCKER_DIR_PATH, exist_ok=True)
        os.makedirs(CHMOCKER_BASE_IMAGES_DIR_PATH, exist_ok=True)
        os.makedirs(CHMOCKER_MOUNT_IMAGES_DIR_PATH, exist_ok=True)

        if not os.path.exists(CHMOKER_INDEX_FILE_PATH):
            with open(CHMOKER_INDEX_FILE_PATH, 'x') as file:
                file.write("{}")

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

    def parse_copy_instr(self, image_tag, command_value):
        if command_value.startswith("--from"):
            previous_stage, src, dst = command_value.split()
            previous_stage = previous_stage.split("--from=")[1]
            image_previous_stage_path = CHMOCKER_BASE_IMAGES_DIR_PATH / Path(f"{previous_stage}.tar")
            tar = tarfile.open(image_previous_stage_path)
            src_path = src.strip("/")
            subdir_and_files = [tarinfo for tarinfo in tar.getmembers() if tarinfo.name.startswith(src_path)]
            if not subdir_and_files:
                raise Exception(f"Path {src} not found in {previous_stage}")
            image_mount_path = CHMOCKER_MOUNT_IMAGES_DIR_PATH / Path(image_tag)
            tar.extractall(path=image_mount_path, members=subdir_and_files)
            tar.close()
        else:
            src, dst = command_value.split()
            raise Exception("Not implemented")

    def parse_instr(self, image_tag, instr):
        command = instr["instruction"]
        if command == "COMMENT":
            return
        if command == "FROM":
            return  # TODO: implement
        full_line = instr["content"].replace("\n", "")
        command_value = instr["value"]
        print(colored(full_line, "yellow"))
        if command == "RUN":
            self.exec_in_chroot(image_tag, command_value)
        elif command == "ADD":
            self.parse_add_instr(image_tag, command_value)
        elif command == "COPY":
            self.parse_copy_instr(image_tag, command_value)

    def unpack_image(self, base_image_tag, new_image_tag, force_refresh=False):
        image_orig_path = CHMOCKER_BASE_IMAGES_DIR_PATH / Path(f"{base_image_tag}.tar")
        image_mount_path = CHMOCKER_MOUNT_IMAGES_DIR_PATH / Path(new_image_tag)
        logging.info(f"Unpacking base image {image_orig_path} to {image_mount_path}")
        if image_mount_path.exists():
            if not force_refresh:
                if base_image_tag != new_image_tag:
                    logging.warning(f"Image {new_image_tag} is already exist, skipping to unpack..")
                return
            if image_orig_path.exists():
                logging.warning(f"Image {new_image_tag} is already exist, removing..")
                self.remove_recursive_force(image_mount_path)
        if not image_orig_path.exists():
            raise Exception(f"Base image {image_orig_path} not found!")
        tar = tarfile.open(image_orig_path)
        tar.extractall(path=image_mount_path)
        tar.close()

    def prepare_chroot(self, image_tag):
        image_mount_path = CHMOCKER_MOUNT_IMAGES_DIR_PATH / Path(image_tag)
        if not image_mount_path.exists():
            raise Exception(f"Image {image_mount_path} not unpacked or not exist!")
        logging.info(f"Addind hardlink to mDNSResponder to {image_tag}")
        image_mount_dns_responder_path = image_mount_path / Path("var/run/mDNSResponder")
        if image_mount_dns_responder_path.exists():
            os.remove(image_mount_dns_responder_path)
        os.link(Path("/var/run/mDNSResponder"), image_mount_dns_responder_path)
        logging.info(f"Mounting devfs to {image_tag}")
        image_devfs_mount_path = image_mount_path / Path("dev")
        os.system(f"mount -t devfs devfs {image_devfs_mount_path}")

    def exec_in_chroot(self, image_tag, command, run_interactive=False, extra_envs=[]):
        image_mount_path = CHMOCKER_MOUNT_IMAGES_DIR_PATH / Path(image_tag)
        env_vars = [
            "HOME=/root",
            'TERM="$TERM"',
            "PS1='\\u:\w\$ '",
            'PATH="/opt/homebrew/bin:/opt/homebrew/sbin${PATH+:$PATH}"',
            "TMPDIR=/tmp",
            "HOMEBREW_CELLAR=/opt/homebrew/Cellar",
            "HOMEBREW_PREFIX=/opt/homebrew",
            "HOMEBREW_REPOSITORY=/opt/homebrew",
            "HOMEBREW_TEMP=/tmp",
            "NONINTERACTIVE=1",
            "SHELL=/bin/bash",
            "CONFIG_SHELL=/bin/bash",
        ]
        env_vars += extra_envs
        env_vars_str = " ".join(env_vars)
        status = os.system(f"chroot {image_mount_path} env -i {env_vars_str} {command}")  # TODO: interactive cond
        print(f"chroot {image_mount_path} env -i {env_vars_str} {command}")
        print(status)
        exit_code = os.waitstatus_to_exitcode(status)
        print(exit_code)
        if exit_code != 0 and not run_interactive:
            raise Exception(f"Command '{command}' exited with code {exit_code}")

    def destroy_chroot(self, image_tag):
        logging.info(f"Destroying chroot of {image_tag}")
        image_mount_path = CHMOCKER_MOUNT_IMAGES_DIR_PATH / Path(image_tag)
        image_mount_dns_responder_path = image_mount_path / Path("var/run/mDNSResponder")
        if image_mount_dns_responder_path.exists():
            logging.info(f"Removing hardlink to mDNSResponder from {image_tag}")
            os.remove(image_mount_dns_responder_path)
        logging.info(f"Umounting devfs from {image_tag}")
        image_devfs_mount_path = image_mount_path / Path("dev")
        os.system(f"umount {image_devfs_mount_path}")

    def write_cache_file(self, file_data: dict, file_obj: TextIO, tag: str, stage_hash: str) -> None:
        logging.info(f"Saving cache data for tag: {tag} and hash: {stage_hash}...")

        file_data[tag] = {'tag': tag, 'hash': stage_hash}
        file_obj.seek(0)
        file_obj.write(json.dumps(file_data))

        logging.info("Cache data saved")

    def save_cache_and_copy_stage(
        self, file_data: dict, file_obj: TextIO, tag: str, stage_hash: str, source_path: Path, destination_path: Path
    ) -> None:
        self.write_cache_file(file_data=file_data, file_obj=file_obj, tag=tag, stage_hash=stage_hash)

        logging.info(f"Copping tar from: {source_path} to: {destination_path}...")
        shutil.copy2(source_path, destination_path)
        logging.info(f"Image tar size {self.get_size_str(destination_path)}")

    def build_stage_if_image_not_exists(
        self, tag_name: str, base_image: str, stage_hash: str, stage_instructions: list
    ) -> None:
        if not os.path.exists(CHMOCKER_BASE_IMAGES_DIR_PATH / Path(f"{tag_name}.tar")):
            logging.info(f"No tar found for tag {tag_name} ")
            self.build_stage(base_image=base_image, image_name=stage_hash, stage_instructions=stage_instructions)
            return

        logging.info(f"Tar for tag {tag_name} already exists, skipping build stage... ")

    def parse_stages(self) -> list:
        logging.info("Parsing stages from the dockerfile...")

        stages = []
        stage_instructions = []
        stage_image_info = (None, None)
        stage_content = ''

        for instruction in DockerfileParser().structure:
            if instruction['instruction'] != 'COMMENT':
                if instruction['instruction'] == 'FROM':
                    if stage_instructions:
                        stages.append(
                            {
                                'image_info': stage_image_info,
                                'instructions': stage_instructions,
                                'content': stage_content,
                                'hash': hashlib.sha256(stage_content.encode('UTF-8')).hexdigest(),
                            }
                        )

                        stage_instructions = []
                        stage_content = ''

                    stage_image_info = parser.image_from(instruction['value'])

                stage_content += instruction['content']
                stage_instructions.append(instruction)
        else:
            stages.append(
                {
                    'image_info': stage_image_info,
                    'instructions': stage_instructions,
                    'content': stage_content,
                    'hash': hashlib.sha256(stage_content.encode('UTF-8')).hexdigest(),
                    'is_last_stage': True,
                }
            )

        logging.info(f"Parsed {len(stages)} stages from the dockerfile")

        return stages

    def build(self):
        logging.info("Starting build process..")

        result_image_tag = self.args.tag

        for stage in self.parse_stages():
            base_image, stage_name = stage['image_info']
            stage_current_hash = stage['hash']

            logging.info(
                f"Checking cache data for the stage with the image {base_image}, "
                f"stage name {stage_name} and hash {stage_current_hash}..."
            )

            if not stage_name and not stage.get('is_last_stage', False):
                if os.path.exists(CHMOCKER_BASE_IMAGES_DIR_PATH / Path(f"{stage_current_hash}.tar")):
                    logging.info(
                        f"Nothing to rebuild for the stage with the image {base_image}, "
                        f" and hash {stage_current_hash}"
                    )
                    logging.info("Skipping build stage...")
                else:
                    self.build_stage(
                        base_image=base_image, image_name=stage_current_hash, stage_instructions=stage['instructions']
                    )

            elif stage_name:
                with open(CHMOKER_INDEX_FILE_PATH, 'r+') as index_file:
                    index_file_json = json.load(index_file)
                    stage_cache_data = index_file_json.get(stage_name)

                    if stage_cache_data:
                        if stage_cache_data['hash'] == stage_current_hash:
                            logging.info(
                                f"Nothing to rebuild for the stage with the image {base_image}, "
                                f" stage name {stage_name} and hash {stage_current_hash}"
                            )

                            if stage.get('is_last_stage', False):  # if it's last stage copy tar with the tag name
                                if not os.path.exists(CHMOCKER_BASE_IMAGES_DIR_PATH / Path(f"{result_image_tag}.tar")):
                                    logging.info(f"No tar found for tag {result_image_tag} ")
                                    self.save_cache_and_copy_stage(
                                        file_data=index_file_json,
                                        file_obj=index_file,
                                        tag=result_image_tag,
                                        stage_hash=stage_current_hash,
                                        source_path=CHMOCKER_BASE_IMAGES_DIR_PATH / Path(f"{stage_current_hash}.tar"),
                                        destination_path=CHMOCKER_BASE_IMAGES_DIR_PATH
                                        / Path(f"{result_image_tag}.tar"),
                                    )
                                else:
                                    logging.info(
                                        f"Tar for tag {result_image_tag} already exists, skipping build stage... "
                                    )

                            continue

                    self.build_stage_if_image_not_exists(
                        tag_name=stage_current_hash,
                        base_image=base_image,
                        stage_hash=stage_current_hash,
                        stage_instructions=stage['instructions'],
                    )
                    self.save_cache_and_copy_stage(
                        file_data=index_file_json,
                        file_obj=index_file,
                        tag=stage_name,
                        stage_hash=stage_current_hash,
                        source_path=CHMOCKER_BASE_IMAGES_DIR_PATH / Path(f"{stage_current_hash}.tar"),
                        destination_path=CHMOCKER_BASE_IMAGES_DIR_PATH / Path(f"{stage_name}.tar"),
                    )

                    if stage.get('is_last_stage', False):  # if it's last stage copy tar with the tag name
                        self.save_cache_and_copy_stage(
                            file_data=index_file_json,
                            file_obj=index_file,
                            tag=result_image_tag,
                            stage_hash=stage_current_hash,
                            source_path=CHMOCKER_BASE_IMAGES_DIR_PATH / Path(f"{stage_current_hash}.tar"),
                            destination_path=CHMOCKER_BASE_IMAGES_DIR_PATH / Path(f"{result_image_tag}.tar"),
                        )

            else:
                with open(CHMOKER_INDEX_FILE_PATH, 'r+') as index_file:
                    index_file_json = json.load(index_file)

                    stage_cache_data = index_file_json.get(result_image_tag)

                    if stage_cache_data:
                        if stage_cache_data['hash'] == stage_current_hash:
                            logging.info(
                                f"Nothing to rebuild for the stage with the image {base_image} "
                                f"and hash {stage_current_hash}"
                            )
                            logging.info("Skipping build stage...")
                            continue

                    self.build_stage_if_image_not_exists(
                        tag_name=stage_current_hash,
                        base_image=base_image,
                        stage_hash=stage_current_hash,
                        stage_instructions=stage['instructions'],
                    )
                    self.save_cache_and_copy_stage(
                        file_data=index_file_json,
                        file_obj=index_file,
                        tag=result_image_tag,
                        stage_hash=stage_current_hash,
                        source_path=CHMOCKER_BASE_IMAGES_DIR_PATH / Path(f"{stage_current_hash}.tar"),
                        destination_path=CHMOCKER_BASE_IMAGES_DIR_PATH / Path(f"{result_image_tag}.tar"),
                    )

                    if stage.get('is_last_stage', False):  # if it's last stage copy tar with the tag name
                        self.save_cache_and_copy_stage(
                            file_data=index_file_json,
                            file_obj=index_file,
                            tag=result_image_tag,
                            stage_hash=stage_current_hash,
                            source_path=CHMOCKER_BASE_IMAGES_DIR_PATH / Path(f"{stage_current_hash}.tar"),
                            destination_path=CHMOCKER_BASE_IMAGES_DIR_PATH / Path(f"{result_image_tag}.tar"),
                        )

    def build_stage(self, base_image, image_name, stage_instructions):
        logging.info(f"Building image with the base image {base_image} and image name {image_name}...")

        image_mount_path = CHMOCKER_MOUNT_IMAGES_DIR_PATH / Path(image_name)
        image_tar_path = CHMOCKER_BASE_IMAGES_DIR_PATH / Path(f"{image_name}.tar")

        self.unpack_image(base_image, image_name, force_refresh=self.args.build_force_refresh)
        self.prepare_chroot(image_name)

        is_failed = False

        try:
            [self.parse_instr(image_name, x) for x in stage_instructions]

        except Exception as error:
            is_failed = True
            if os.path.exists(image_tar_path):
                self.remove_recursive_force(image_tar_path)

            logging.exception(
                f"Exception occurred building image with the base image {base_image} and " f"image name {image_name}"
            )
            raise error

        finally:
            self.destroy_chroot(image_name)
            if not self.args.build_no_tar and not is_failed:
                self.create_tar_archive(image_tar_path, image_mount_path)
            if not self.args.build_no_remove:
                self.remove_recursive_force(image_mount_path)

    def create_tar_archive(self, tar_path, source_path):
        logging.info(f"Creating tar archive {tar_path}..")
        tar = tarfile.open(tar_path, "w")
        for root_dir_item in os.listdir(source_path):
            root_dir_item_path = source_path / Path(root_dir_item)
            tar.add(root_dir_item_path, root_dir_item)
        tar.close()
        logging.info(f"Image tar size {self.get_size_str(tar_path)}")

    def copy_dyld_libs_to_image(self, image_mount_path):
        lib_target_dir = image_mount_path / Path("System/Library/dyld")
        os.makedirs(lib_target_dir, exist_ok=True)
        for lib in glob.glob("/System/Volumes/Preboot/Cryptexes/OS/System/Library/dyld/dyld_shared_cache_*"):
            logging.info(f"Copying {lib} to {lib_target_dir}/..")
            self.copy_with_metadata(lib, f"{lib_target_dir}/")

    def copy_system_to_image(self, image_mount_path):
        for path in CHMOCKER_SYSTEM_IMAGE_PATHS:
            target_path = image_mount_path / Path(path.strip("/"))  # removing leading slash
            target_dir = target_path.parents[0]
            logging.info(f"Copying {path} to {target_dir}/..")
            os.makedirs(target_dir, exist_ok=True)
            self.copy_with_metadata(path, f"{target_dir}/")

    def copy_command_line_tools_to_image(self, image_mount_path):
        logging.info(f"Copying command line tools to {image_mount_path}/..")
        # Temp function to override my system cmd tools to version 11.3
        cmd_tools_dst_path = image_mount_path / Path("Library/Developer/CommandLineTools/")
        os.makedirs(cmd_tools_dst_path, exist_ok=True)
        self.copy_with_metadata(Path("CommandLineTools11/*"), f"{cmd_tools_dst_path}/")

    def create_system_stuff(self, image_mount_path):
        os.makedirs(image_mount_path / Path("root"), exist_ok=True)
        os.makedirs(image_mount_path / Path("var/run"), exist_ok=True)
        os.makedirs(image_mount_path / Path("dev"), exist_ok=True)
        os.makedirs(image_mount_path / Path("private/tmp"), exist_ok=True)
        tmp_dir_path = image_mount_path / Path("tmp")
        if tmp_dir_path.exists():
            self.remove_recursive_force(tmp_dir_path)
        os.symlink("/private/tmp", tmp_dir_path)
        docker_env_path = image_mount_path / Path(".dockerenv")
        docker_env_path.touch()

    def create_system_image(self):
        image_mount_path = CHMOCKER_MOUNT_IMAGES_DIR_PATH / Path(self.args.tag)
        if image_mount_path.exists():
            if not self.args.image_recreate:
                logging.warning(
                    f"Image {self.args.tag} is already created, skipping.. " "Use '--recreate' flag to recreate"
                )
                return
        logging.info(f"Creating image {self.args.tag}..")
        image_tar_path = CHMOCKER_BASE_IMAGES_DIR_PATH / Path(f"{self.args.tag}.tar")
        self.copy_dyld_libs_to_image(image_mount_path)
        self.copy_system_to_image(image_mount_path)
        # self.copy_command_line_tools_to_image(image_mount_path)
        self.create_system_stuff(image_mount_path)
        if not self.args.image_no_brew:
            self.install_brew_into_image(image_mount_path)
        if not self.args.image_no_tar:
            self.create_tar_archive(image_tar_path, image_mount_path)
        if not self.args.image_no_remove:
            self.remove_recursive_force(image_mount_path)

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
        self.unpack_image(self.args.tag, self.args.tag, self.args.run_force_refresh)
        self.prepare_chroot(self.args.tag)
        self.exec_in_chroot(
            self.args.tag,
            self.args.command,
            self.args.run_interactive,
            self.args.run_extra_envs,
        )
        self.destroy_chroot(self.args.tag)
        if self.args.run_remove_after:
            image_mount_path = CHMOCKER_MOUNT_IMAGES_DIR_PATH / Path(self.args.tag)
            self.remove_recursive_force(image_mount_path)

            # with open(CHMOKER_INDEX_FILE_PATH, 'r+') as index_file:
            #     index_file_json = json.load(index_file)
            #
            #     stage_data = index_file_json.get(self.args.tag)
            #
            #     stage_hash = stage_data['hash']
            #
            # self.unpack_image(stage_hash, stage_hash, self.args.run_force_refresh)
            # self.prepare_chroot(stage_hash)
            # self.exec_in_chroot(
            #     stage_hash,
            #     self.args.command,
            #     self.args.run_interactive,
            #     self.args.run_extra_envs,
            # )
            # self.destroy_chroot(stage_hash)
            # if self.args.run_remove_after:
            #     image_mount_path = CHMOCKER_MOUNT_IMAGES_DIR_PATH / Path(stage_hash)
            #     self.remove_recursive_force(image_mount_path)

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
