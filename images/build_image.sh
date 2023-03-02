#!/bin/bash

NUM_ARGS=1
# TODO: should be handsonsecurity
IMAGE_OWNER="hunhoffe"
IMAGES=("seedemu" "seedemu-tor" "seedemu-botnet" "seedemu-eth")
OUTPUT_DIR="output"
USAGE="
Usage: ./build_image.sh <image_name>
    Valid image names are: ${IMAGES[*]}
"

# Check the min number of arguments
if [ $# != $NUM_ARGS ]; then
    echo "***Error: Expected at least $NUM_ARGS arguments."
    echo "$USAGE"
    exit -1
fi

if [[ ! " ${IMAGES[*]} " =~ " $1 " ]]; then
    echo "***Error: Unknown image name."
    echo "$USAGE"
    exit -1
fi

python3 build_image.py $1 $IMAGE_OWNER -o ${OUTPUT_DIR}_$1
cd ${OUTPUT_DIR}_$1
docker build -t $IMAGE_OWNER/$1 .
