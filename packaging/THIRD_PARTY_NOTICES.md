# Third-party notices

The bundled model is DINOv2 ViT-S/14, copyright Meta Platforms, Inc., licensed under
Apache License 2.0. The image contains the official checkpoint provenance
`facebook/dinov2-small@ed25f3a31f01632728cabb09d1542f84ab7b0056` and the exact ONNX
Community conversion artifact
`onnx-community/dinov2-small@8b1f705a3a7f6f062f6bdd21986c1583d3ef105d`,
SHA-256 `dfce54a839b491f395c516350ebb4a78f947e9170a6beac0f2bc5638e0f09d61`.
The full model licence is installed at
`/opt/growspace-vision/licenses/DINOv2-APACHE-2.0.txt`.

ONNX Runtime 1.29.0 is licensed under the MIT licence. Its wheel installs the complete
`onnxruntime/LICENSE` and `onnxruntime/ThirdPartyNotices.txt` files in the application
virtual environment. The remaining Python wheel licences stay in their installed
`.dist-info/licenses` directories. Debian package copyright files stay under
`/usr/share/doc`, as supplied by the locked Debian snapshot packages.

FlatBuffers 25.12.19 is licensed under Apache License 2.0. Its wheel declares that
licence but carries no licence text, so the immutable release text is installed at
`/opt/growspace-vision/licenses/FlatBuffers-APACHE-2.0.txt`.

The service source is licensed under the repository's MIT `LICENSE`.
