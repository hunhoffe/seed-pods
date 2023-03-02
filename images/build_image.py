import argparse
import os
from pathlib import Path
import shutil
from seedemu import get_seedemu_image, get_seedemu_tor_image, get_seedemu_botnet_image, get_seedemu_eth_image

SEED_IMAGES = {
    "seedemu": get_seedemu_image,
    "seedemu-tor": get_seedemu_tor_image,
    "seedemu-botnet": get_seedemu_botnet_image,
    "seedemu-eth": get_seedemu_eth_image,
}

def build_image(image_builder, image_owner, output_dir):
    # Remove output directory if it already exists
    output_path = Path(output_dir)
    if output_path.exists():
        shutil.rmtree(output_path)

    # Create output directory and chdir there so created files are placed in the directory
    os.mkdir(output_dir)
    orig_cwd = os.getcwd()
    os.chdir(output_dir)

    # Create locally, this is so we can push it to docker from here after it's built
    image = image_builder(image_owner)
    image.generateImageSetup(useRunCommand=False)

    # Restore working direcotry
    os.chdir(orig_cwd)

parser = argparse.ArgumentParser("build_image")
parser.add_argument("image_name", help="The name of the image to build", type=str, choices=SEED_IMAGES.keys())
parser.add_argument("image_owner", help="The owner of the image (dockerhub user)", type=str, default="handsonsecurity")
parser.add_argument('-o', "--output_dir", help="Output directory for image files.", type=str, default='output')
args = parser.parse_args()
build_image(SEED_IMAGES[args.image_name], args.image_owner, args.output_dir)
