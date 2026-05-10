#!/bin/bash

# Define paths
DEPLOY_DIR="/home/brayschway/Emulators"
BUILD_SOURCE="./dist/controller-manager-1.0.0.AppImage"
TARGET_NAME="controller-manager.AppImage"

# Ensure the deployment directory exists
if [ ! -d "$DEPLOY_DIR" ]; then
    echo "Error: Directory $DEPLOY_DIR does not exist."
    exit 1
fi

echo "Starting update process..."

# 1. In /home/Emulators, delete the .stable file.
if [ -f "$DEPLOY_DIR/.stable" ]; then
    echo "Deleting old .stable file..."
    rm "$DEPLOY_DIR/.stable"
fi

# 2. Rename the remaining file to .stable (replacing the deleted one).
# We search for the AppImage file that isn't the hidden .stable file.
REMAINING_FILE=$(ls "$DEPLOY_DIR" | grep ".AppImage" | head -n 1)

if [ -n "$REMAINING_FILE" ]; then
    echo "Renaming $REMAINING_FILE to .stable..."
    mv "$DEPLOY_DIR/$REMAINING_FILE" "$DEPLOY_DIR/.stable"
else
    echo "No existing AppImage found to rotate into .stable."
fi

# 3. Make a copy of ./dist/controller-manager-1.0.0.AppImage and save it to /home/Emulators, removing the -1.0.0.
if [ -f "$BUILD_SOURCE" ]; then
    echo "Copying new build to $DEPLOY_DIR/$TARGET_NAME..."
    cp "$BUILD_SOURCE" "$DEPLOY_DIR/$TARGET_NAME"
    chmod +x "$DEPLOY_DIR/$TARGET_NAME"
    echo "Successfully updated to 1.0.0"
else
    echo "Error: $BUILD_SOURCE not found. Please ensure the build is in the dist/ folder."
    exit 1
fi
