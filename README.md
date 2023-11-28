# Chmocker

Chmocker (chroot + docker) is yet another try to create MacOS containers. Chmocker accepts the classic Dockerfile format and allows you to have an isolated environment on MacOS computers. Created for building [Flipper Zero Embedded toolchain]()

## How it works
- FS layers made through tar images (very slow, way to discover - [APFS snapshots](https://github.com/ahl/apfs/tree/master))
- FS isolation made through chroot
- Process isolation is absent (way to discover - [Process groups](https://jmmv.dev/2019/11/wait-for-process-group-darwin.html))

## How to use
### Images
All begins with the base system image. In first you need to create it from your system, or download it from somewhere.
```bash
sudo chmocker image create -t MacOSVenturaWithBrew
```
This command will build a chroot-ready .tar archive, jump to it and install [Brew](https://brew.sh). Try using `-h` flag to see extended flags, e.g. for skipping brew install or adding a custom ComandLineTools.

### Dockerfile
You can try to build something inside a chroot of the image created above.
Example Dockerfile:

```Dockerfile
FROM MacOSVenturaWithBrew
RUN brew install coreutils
ADD https://www.python.org/ftp/python/3.11.2/Python-3.11.2.tgz /toolchain/src/src/archives/
RUN tar -xvf /toolchain/src/src/archives/Python-3.11.2.tgz -C /toolchain/src/src/
ADD scripts/build-mac-python.sh /toolchain/src/
RUN bash /toolchain/src/build-mac-python.sh
```

### Build
```bash
sudo chmocker build -t macos-python
```

### Run
```bash
sudo chmocker run --rm --it macos-python
```
