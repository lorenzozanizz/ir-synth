"""



"""


import numpy as np

# Namespace class
class PhysicsFunc:
    """

    """

    @staticmethod
    def apply_emissivity(l_surface: np.ndarray, eps, l_reflected) -> np.ndarray:
        """ L_apparent = eps*B(T_surf) + (1-eps)*B(T_reflected). eps and
        l_reflected broadcast (scalars or per-pixel/per-vertex maps), and B is the
        radiated Boltzmann thermal energy

        For more resources:
        https://www.flir.com/discover/professional-tools/how-does-emissivity-affect-thermal-imaging/

        :param l_surface: emitted energy of the surface,
        :param eps: emissivity of the surface,
        :param l_reflected: reflected energy
        """
        eps = np.asarray(eps, dtype=np.float64)
        return eps * l_surface + (1.0 - eps) * np.asarray(l_reflected)

    @staticmethod
    def planck_law(t: np.ndarray) -> np.ndarray:
        pass
