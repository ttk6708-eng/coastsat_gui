# Third-party notices — native desktop edition

CoastSat is by Kilian Vos and contributors: https://github.com/kvos/CoastSat.
CoastSat and this application wrapper are distributed under GPL-3.0. See LICENSE.
Application and wrapper source is included alongside the executable, with build instructions.

The runtime is based on Python Software Foundation's official Python 3.12.10 NuGet package.
Python license files are retained in env. GDAL's Windows wheel is from Christoph Gohlke's
geospatial-wheels release v2026.8.20. See the pinned URL in requirements-native.lock.txt.

Qt / PySide6 Essentials and Shiboken6 provide native widgets. They are dynamically loaded from
the supplied runtime. Their licenses and notices are retained in package metadata and the Qt
package. The library files remain replaceable. Upstream source and licensing information:
https://code.qt.io/cgit/pyside/pyside-setup.git/ and https://www.qt.io/licensing/open-source-lgpl-obligations
The application uses only Qt Widgets/Core/Gui and does not use Qt WebEngine.

Noto Sans KR is provided under the SIL Open Font License 1.1. The original font and OFL.txt
are included in assets/fonts. Source: https://github.com/google/fonts/tree/main/ofl/notosanskr
The font is loaded for the application only; it is not installed into Windows.

NumPy, SciPy, pandas, Pillow, Matplotlib, scikit-image, scikit-learn, GeoPandas, Astropy,
GDAL/PROJ, Earth Engine Python API, PyInstaller and transitive dependency licenses are
retained with their installed packages. See requirements-native.lock.txt for versions.
PyInstaller's bootloader exception permits distribution of the frozen launcher.

No user imagery, account credentials, service-account keys or authentication tokens are included.

AI optional edition: OmniCloudMask 1.7.1 (Nick Wright / DPIRD, MIT), weights from
https://huggingface.co/NickWright/OmniCloudMask (MIT, revision c9a4fb88188709127aa25cfe51ae7fd41b0132f8).
Weight hashes are pinned in desktop/ai_models.py. OmniCloudMask license is included under licenses/.
PyTorch / torchvision (BSD), timm (Apache-2.0), segmentation-models-pytorch (MIT),
safetensors, rasterio and their dependency notices remain in env/Lib/site-packages package metadata.
Upstream: https://github.com/DPIRD-DMA/OmniCloudMask, https://github.com/pytorch/pytorch,
https://github.com/pytorch/vision, https://github.com/huggingface/pytorch-image-models,
https://github.com/qubvel-org/segmentation_models.pytorch. See requirements-ai.lock.txt.
