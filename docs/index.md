# Thermal

Thermal is a Blender extension for physics based thermal simulation and rendering. It creates synthetic thermal imaging data from a normal 3D scene. You set a temperature on each object, and the add-on turns that temperature into a rendered thermal image.

The add-on is also known by its internal identifier, bl_thermal. It works with Blender 4.5 and later.

## What this documentation covers

This site has two main documents.

<iframe src="viewer/index.html" style="width: 100%; height: 500px; border: none;"></iframe>

- Physics: describes how the add-on converts a surface temperature into a signal that a sensor would record. It covers the Wien approximation, the Rayleigh-Jeans approximation, the calibration model used by real long-wave infrared cameras, and the Stefan-Boltzmann law. It also covers how emissivity is applied.
- Architecture: describes how the code is organized. It covers the separation between the pure physics code and the Blender specific code, the temperature field pipeline, and the shader construction used for rendering.

## Where to start

If you want to understand the math behind the render, read the physics document. If you want to understand how the code is structured, read the architecture document.

## Project status

The add-on is at version 0.9.0. Some parts of the code are placeholders for future work. This is noted in the relevant sections of the documents.