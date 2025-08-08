#/bin/bash
if ! command -v unzip &> /dev/null; then
    echo "unzip could not be found, please install it to continue."
    exit 1
fi
echo "Downloading the latest release of tum..."
curl -fsSL "https://github.com/m5kro/tum/releases/download/1.0.1/tum.zip" -o tum.zip
echo "Unzipping the downloaded file..."
unzip -o tum.zip -d $HOME/.local/share/
echo "Making the tum script executable..."
chmod +x $HOME/.local/share/tum/tum
echo "linking the tum script to /usr/local/bin..."
ln -sf $HOME/.local/share/tum/tum $HOME/.local/bin/tum
echo "Cleaning up..."
rm -rf tum.zip
echo "Installation complete! You can now run tum from anywhere by typing 'tum' in your terminal."