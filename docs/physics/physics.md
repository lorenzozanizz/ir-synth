# Physics

This document explains how Thermal converts a surface temperature into a signal that a thermal sensor would record. It also explains how emissivity changes the result.

## The general idea

A thermal camera does not measure temperature directly. A thermal camera measures radiated power in a limited band of wavelengths. The add-on must convert a temperature, in Kelvin, into a signal value. This conversion is called a transfer function.

Thermal offers several transfer functions. Each one is an approximation of Planck's law of black body radiation. The approximations differ in accuracy and in speed. Some approximations are only valid within a certain temperature range.

All temperatures in the code are stored in Kelvin. The user interface can show Celsius or Fahrenheit, but the add-on converts these values to Kelvin before any calculation.

## The Wien approximation

The Wien approximation applies when the exponential term in Planck's law is much larger than one. This condition is true for short wavelengths or for low temperatures. The formula is:

S(T) = R times exp(minus B divided by T) plus O

In this formula:

- S is the output signal.
- T is the surface temperature, in Kelvin.
- R is a scale factor. R absorbs the physical constants, the width of the sensor band, and the gain of the detector.
- B is an exponential coefficient, in Kelvin. B equals h times c divided by (lambda times k), where lambda is the center wavelength of the sensor band.
- O is a constant offset. O represents the dark signal of the detector.

The Wien approximation loses accuracy as the temperature increases. At high temperatures, the exact narrow band form should be used instead.

## The Rayleigh-Jeans approximation

The Rayleigh-Jeans approximation applies at the opposite end of the range from the Wien approximation. It is valid when B divided by T is much smaller than one. This condition is true for long wavelengths or for high temperatures. The formula is:

S(T) = R times T plus O

This formula is linear in temperature. It has no exponential term, so it is fast to calculate. It becomes less accurate as the temperature drops or as the center wavelength becomes shorter.

## The calibration model, named RBFO

Real long-wave infrared cameras, for example the FLIR AX5, do not report their calibration in terms of R and B alone. They report four constants: R, B, F, and O. The formula is:

S(T) = R divided by (exp(B divided by T) minus F) plus O

F is close to one. F corrects for the fact that the sensor band is not infinitely narrow. When F is zero, this formula becomes the same as the exact narrow band form of Planck's law. The RBFO model stays accurate across a wider temperature range than the Wien approximation, because it keeps the full exponential term instead of a simpler expansion.

If F is greater than one, the denominator of the formula can reach zero. At that point the model becomes invalid. The add-on calculates the highest safe temperature for this case, so that this condition can be reported to the user before it happens.

## The Stefan-Boltzmann law

The Stefan-Boltzmann law gives the total radiated power across all wavelengths, not just one band. The formula is:

M = epsilon times sigma times T to the fourth power

In this formula, M is the total radiant emittance, epsilon is the emissivity of the surface, sigma is the Stefan-Boltzmann constant, and T is the temperature in Kelvin. This transfer type is defined in the code as an option, but its numeric evaluator is not implemented yet. Only the Wien, Rayleigh-Jeans, and RBFO transfer functions are implemented at this time.

## Recovering temperature from a signal

Each implemented transfer function can also work in reverse. Given a signal value, the add-on can calculate the temperature that produced it. This reverse calculation is used to label the legend of the false color display, after the display has been normalized in signal space.

## Emissivity

A real surface does not radiate as much energy as an ideal black body at the same temperature. The fraction of energy that a surface actually radiates is called its emissivity. The remaining energy that reaches the sensor comes from the surroundings, reflected off the surface. The apparent signal seen by the sensor is:

S apparent = epsilon times S(T surface) plus (1 minus epsilon) times S(T reflected)

Here, epsilon is the emissivity value, between zero and one. S(T surface) is the transfer function applied to the true surface temperature. S(T reflected) is the transfer function applied to the temperature of the reflected surroundings. This mix happens after the transfer function, in signal space, not in temperature space.

## Numerical safety

Some formulas divide by temperature or raise an exponential term. To avoid errors from a temperature of zero, the add-on clamps every temperature to a small positive minimum before it enters a transfer function. To avoid the exponential term producing an infinite value, the add-on limits the maximum exponent that it will calculate. These two safeguards let the add-on handle bad input data without crashing or producing invalid images.
