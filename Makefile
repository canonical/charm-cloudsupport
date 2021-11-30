PYTHON := /usr/bin/python3

PROJECTPATH=$(dir $(realpath $(MAKEFILE_LIST)))
ifndef CHARM_BUILD_DIR
	CHARM_BUILD_DIR=${PROJECTPATH}.build
endif
METADATA_FILE="metadata.yaml"
CHARM_NAME=$(shell cat ${PROJECTPATH}/${METADATA_FILE} | grep -E '^name:' | awk '{print $$2}')

help:
	@echo "This project supports the following targets"
	@echo ""
	@echo " make help - show this text"
	@echo " make clean - remove unneeded files"
	@echo " make submodules - make sure that the submodules are up-to-date"
	@echo " make submodules-update - update submodules to latest changes on remote branch"
	@echo " make build - build the charm"
	@echo " make release - run clean, submodules and build targets"
	@echo " make lint - run flake8 and black --check"
	@echo " make black - run black and reformat files"
	@echo " make proof - run charm proof"
	@echo " make functional - run the tests defined in the functional subdirectory"
	@echo " make test - run lint, proof, and functional targets"
	@echo ""

clean:
	@echo "Cleaning files"
	@git clean -ffXd -e '!.idea'
	@echo "Cleaning existing build"
	@rm -rf ${CHARM_BUILD_DIR}/${CHARM_NAME}

submodules:
	@echo "Cloning submodules"
	@git submodule update --init --recursive

submodules-update:
	@echo "Pulling latest updates for submodules"
	@git submodule update --init --recursive --remote --merge

build:
	@echo "Building charm to base directory ${CHARM_BUILD_DIR}/${CHARM_NAME}"
	@-git rev-parse --abbrev-ref HEAD > ./repo-info
	@-git describe --always > ./version
	@mkdir -p ${CHARM_BUILD_DIR}
	@tox -e build
	@mv ${CHARM_NAME}.charm ${CHARM_BUILD_DIR}
	@echo "Charm can be found at ${CHARM_BUILD_DIR}/${CHARM_NAME}.charm"


release: clean build unpack
	@echo "Charm is built and unpacked at ${CHARM_BUILD_DIR}/${CHARM_NAME}"

unpack: build
	@-rm -rf ${CHARM_BUILD_DIR}/${CHARM_NAME}
	@mkdir -p ${CHARM_BUILD_DIR}/${CHARM_NAME}
	@echo "Unpacking built .charm into ${CHARM_BUILD_DIR}/${CHARM_NAME}"
	@cd ${CHARM_BUILD_DIR}/${CHARM_NAME} && unzip -q ${CHARM_BUILD_DIR}/${CHARM_NAME}.charm
	# until charmcraft copies READMEs in, we need to publish charms with readmes in them.
	@cp ${PROJECTPATH}/README.md ${CHARM_BUILD_DIR}/${CHARM_NAME}
	@cp ${PROJECTPATH}/copyright ${CHARM_BUILD_DIR}/${CHARM_NAME}
	@cp ${PROJECTPATH}/repo-info ${CHARM_BUILD_DIR}/${CHARM_NAME}
	@cp ${PROJECTPATH}/version ${CHARM_BUILD_DIR}/${CHARM_NAME}

lint:
	@echo "Running lint checks"
	@tox -e lint

reformat:
	@echo "Reformat files with black and isort"
	@tox -e reformat

proof: unpack
	@echo "Running charm proof"
	@charm proof ${CHARM_BUILD_DIR}/${CHARM_NAME}

functional: build
	@echo "Executing functional tests in ${CHARM_BUILD_DIR}"
	@CHARM_BUILD_DIR=${CHARM_BUILD_DIR} tox -e func

smoke: build 
	@echo "Executing smoke tests in ${CHARM_BUILD_DIR}"
	@CHARM_BUILD_DIR=${CHARM_BUILD_DIR} tox -e func-smoke

test: lint proof functional
	@echo "Tests completed for charm ${CHARM_NAME}."

# The targets below don't depend on a file
.PHONY: help submodules submodules-update clean build release lint black proof functional test unpack
