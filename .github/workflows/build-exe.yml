name: Build EXE

on:
  workflow_dispatch:
    inputs:
      tag:
        description: 'Release tag (e.g. v1.0.0). Leave empty to skip releasing.'
        required: false
        default: ''
        type: string

permissions:
  contents: write

jobs:
  build:
    runs-on: windows-latest

    steps:
      - name: Checkout
        uses: actions/checkout@v4

      - name: Set up Python
        uses: actions/setup-python@v5
        with:
          python-version: '3.11'
          cache: 'pip'

      - name: Install deps
        run: |
          python -m pip install --upgrade pip
          pip install -r requirements.txt

      - name: Build EXE with PyInstaller
        run: pyinstaller --noconfirm --clean --onefile --windowed --name "PSP2PS4_GUI" --collect-all customtkinter --add-data "emulator_options.json;." main.py

      - name: Show output
        run: dir dist

      - name: Upload artifact (expires in 2 days)
        uses: actions/upload-artifact@v4
        with:
          name: PSP2PS4_GUI
          path: dist/PSP2PS4_GUI.exe
          retention-days: 2
          if-no-files-found: error

      - name: Attach to Release (if tag given)
        if: ${{ inputs.tag != '' }}
        uses: softprops/action-gh-release@v2
        with:
          tag_name: ${{ inputs.tag }}
          files: dist/PSP2PS4_GUI.exe
          generate_release_notes: true
