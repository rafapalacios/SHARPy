import numpy as np
import importlib
import unittest
import os


class TestGeradinXbeam(unittest.TestCase):
    """
    Tests the xbeam library for the geradin clamped beam
    Validation values taken from
    Simpson, R.J. and Palacios, R., 2013.
    Numerical aspects of nonlinear flexible aircraft flight dynamics modeling.
    In 54th AIAA/ASME/ASCE/AHS/ASC Structures, Structural Dynamics, and Materials Conference (p. 1634).
    """

    @classmethod
    def setUpClass(cls):
        # run all the cases generators
        case = 'geradin'
        mod = importlib.import_module('tests.xbeam.' + case + '.generate_' + case)

    @classmethod
    def tearDownClass(cls):
        pass

    def test_geradin(self):
        import sharpy.sharpy_main
        # suppress screen output
        solver_path = os.path.abspath(os.path.dirname(os.path.realpath(__file__)) + '/geradin/geradin.solver.txt')
        sharpy.sharpy_main.main(['', solver_path])

        # read output and compare
        output_path = os.path.dirname(solver_path) + '/beam/'
        # pos_def
        pos_data = np.genfromtxt(output_path + 'beam_geradin_000000.csv')
        self.assertAlmostEqual(pos_data[-1, 2], -2.159, 2)
        self.assertAlmostEqual(5.0 - pos_data[-1, 0], 0.596, 3)
        # psi_def
        psi_data = np.genfromtxt(output_path + 'beam_geradin_crv_000000.csv')
        self.assertAlmostEqual(psi_data[-1, 1], 0.6720, 3)


class TestDynamic2dXbeam(unittest.TestCase):
    """
    Tests the xbeam library for the dynamic 2d beam
    Validation values taken from...
    """

    @classmethod
    def setUpClass(cls):
        # run all the cases generators
        case = 'dynamic2d'
        mod = importlib.import_module('tests.xbeam.' + case + '.generate_' + case)

    @classmethod
    def tearDownClass(cls):
        pass

    def test_dynamic2d(self):
        import sharpy.sharpy_main
        # suppress screen output
        # sharpy.sharpy_main.cout.cout_quiet()
        solver_path = os.path.abspath(os.path.dirname(os.path.realpath(__file__)) + '/dynamic2d/dynamic2d.solver.txt')
        sharpy.sharpy_main.main(['', solver_path])
        # sharpy.sharpy_main.cout.cout_talk()

        # read output and compare
        output_path = os.path.dirname(solver_path) + '/beam/'
        pos_data = np.genfromtxt(output_path + 'beam_dynamic2d_glob_000999.csv')
        self.assertAlmostEqual(pos_data[-1, 0], -3.7350, 3)
        self.assertAlmostEqual(pos_data[-1, 1], 13.9267, 3)
