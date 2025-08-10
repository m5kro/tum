#!/bin/bash
if ! command -v unzip &> /dev/null; then
    echo "unzip could not be found, please install it to continue."
    exit 1
fi

if [[ $(uname -m) != "x86_64" ]]; then
    echo "This build is intended for x86_64 systems only. You are running on $(uname -m)."
    echo "Please manually build from source if you need to run on this architecture."
    echo "Instructions for building from source can be found at https://github.com/m5kro/tum#how-to-build"
    exit 1
fi
echo "Downloading the latest release of tum..."
curl -fsSL "https://github.com/m5kro/tum/releases/download/1.0.1/tum.zip" -o tum.zip
echo "Unzipping the downloaded file..."
sudo unzip -o tum.zip -d /usr/local/share/
echo "Making tum executable..."
sudo chmod +x /usr/local/share/tum/tum
echo "Linking tum to /usr/local/bin..."
sudo ln -sf /usr/local/share/tum/tum /usr/local/bin/tum
echo "Cleaning up..."
rm -rf tum.zip
echo "Installation complete! You can now run tum from anywhere by typing 'tum' in your terminal."