import ctypes as ct
import numpy as np

from sharpy.structure.basestructure import BaseStructure
import sharpy.structure.models.beamstructures as beamstructures
import sharpy.utils.algebra as algebra
from sharpy.utils.datastructures import StructTimeStepInfo


class Beam(BaseStructure):
    def __init__(self):
        self.settings = None
        # basic info
        self.num_node_elem = -1
        self.num_node = -1
        self.num_elem = -1

        self.timestep_info = []
        self.ini_info = None
        self.dynamic_input = []

        self.connectivities = None

        self.elem_stiffness = None
        self.stiffness_db = None
        self.inv_stiffness_db = None
        self.n_stiff = 0

        self.elem_mass = None
        self.mass_db = None
        self.n_mass = 0

        self.frame_of_reference_delta = None
        self.structural_twist = None
        self.boundary_conditions = None
        self.beam_number = None

        self.lumped_mass = None
        self.lumped_mass_nodes = None
        self.lumped_mass_inertia = None
        self.lumped_mass_position = None
        self.n_lumped_mass = 0

        self.steady_app_forces = None

        self.elements = []

        self.master = None
        self.node_master_elem = None

        self.vdof = None
        self.fdof = None
        self.num_dof = 0

        self.fortran = dict()

    def generate(self, in_data, settings):
        self.settings = settings
        # read and store data
        # type of node
        self.num_node_elem = in_data['num_node_elem']
        # node info
        self.num_node = in_data['num_node']
        self.num_elem = in_data['num_elem']
        # ini info
        self.ini_info = StructTimeStepInfo(self.num_node, self.num_elem, self.num_node_elem)
        # attention, it has to be copied, not only referenced
        self.ini_info.pos = in_data['coordinates'].astype(dtype=ct.c_double, order='F')

        # connectivity information
        self.connectivities = in_data['connectivities'].astype(dtype=ct.c_int, order='F')

        # stiffness data
        self.elem_stiffness = in_data['elem_stiffness'].copy()
        self.stiffness_db = in_data['stiffness_db'].copy()
        (self.n_stiff, _, _) = self.stiffness_db.shape
        self.inv_stiffness_db = np.zeros_like(self.stiffness_db, dtype=ct.c_double, order='F')
        for i in range(self.n_stiff):
            self.inv_stiffness_db[i, :, :] = np.linalg.inv(self.stiffness_db[i, :, :])

        # mass data
        self.elem_mass = in_data['elem_mass'].copy()
        self.mass_db = in_data['mass_db'].copy()
        (self.n_mass, _, _) = self.mass_db.shape

        # frame of reference delta
        self.frame_of_reference_delta = in_data['frame_of_reference_delta'].copy()
        # structural twist
        self.structural_twist = in_data['structural_twist'].copy()
        # boundary conditions
        self.boundary_conditions = in_data['boundary_conditions'].copy()
        # beam number for every elem
        try:
            self.beam_number = in_data['beam_number'].copy()
        except KeyError:
            self.beam_number = np.zeros((self.num_elem, ), dtype=int)

        # applied forces
        self.steady_app_forces = np.zeros((self.num_node, 6))
        try:
            self.steady_app_forces = in_data['app_forces'].copy()
        except KeyError:
            pass

        # generate the Element array
        for ielem in range(self.num_elem):
            self.elements.append(
                beamstructures.Element(
                    ielem,
                    self.num_node_elem,
                    self.connectivities[ielem, :],
                    self.ini_info.pos[self.connectivities[ielem, :], :],
                    self.frame_of_reference_delta[ielem, :, :],
                    self.structural_twist[self.connectivities[ielem, :]],
                    self.beam_number[ielem],
                    self.elem_stiffness[ielem],
                    self.elem_mass[ielem]))
        # now we need to add the attributes like mass and stiffness index
        for ielem in range(self.num_elem):
            dictionary = dict()
            dictionary['stiffness_index'] = self.elem_stiffness[ielem]
            dictionary['mass_index'] = self.elem_mass[ielem]
            self.elements[ielem].add_attributes(dictionary)

        # psi calculation
        self.generate_psi()

        # master-slave structure
        self.generate_master_structure()

        # the timestep_info[0] is the steady state or initial state for unsteady solutions
        self.ini_info.steady_applied_forces = self.steady_app_forces.astype(dtype=ct.c_double, order='F')
        # rigid body rotations
        self.ini_info.update_orientation(self.settings['orientation'])
        self.timestep_info.append(self.ini_info.copy())
        self.timestep_info[-1].steady_applied_forces = self.steady_app_forces.astype(dtype=ct.c_double, order='F')

        # lumped masses
        try:
            self.lumped_mass = in_data['lumped_mass'].copy()
        except KeyError:
            self.lumped_mass = None
        else:
            self.lumped_mass_nodes = in_data['lumped_mass_nodes'].copy()
            self.lumped_mass_inertia = in_data['lumped_mass_inertia'].copy()
            self.lumped_mass_position = in_data['lumped_mass_position'].copy()
            self.n_lumped_mass, _ = self.lumped_mass_position.shape
        # lumped masses to element mass
        if self.lumped_mass is not None:
            self.lump_masses()

        self.generate_dof_arrays()
        self.generate_fortran()

    def generate_psi(self):
        # it will just generate the CRV for all the nodes of the element
        self.ini_info.psi = np.zeros((self.num_elem, 3, 3), dtype=ct.c_double, order='F')
        for elem in self.elements:
            self.ini_info.psi[elem.ielem, :, :] = elem.psi_ini

    def add_unsteady_information(self, dyn_dict, num_steps):
        # data storage for time dependant output
        for it in range(num_steps):
            self.add_timestep(self.timestep_info)
        self.timestep_info[0] = self.ini_info.copy()

        # data storage for time dependant input
        for it in range(num_steps):
            self.dynamic_input.append(dict())

        try:
            for it in range(num_steps):
                self.dynamic_input[it]['dynamic_forces'] = dyn_dict['dynamic_forces'][it, :, :]
        except KeyError:
            for it in range(num_steps):
                self.dynamic_input[it]['dynamic_forces'] = np.zeros((self.num_node, 6), dtype=ct.c_double, order='F')

    def generate_dof_arrays(self):
        self.vdof = np.zeros((self.num_node,), dtype=ct.c_int, order='F') - 1
        self.fdof = np.zeros((self.num_node,), dtype=ct.c_int, order='F') - 1

        vcounter = -1
        fcounter = -1
        for inode in range(self.num_node):
            if self.boundary_conditions[inode] == 0:
                vcounter += 1
                fcounter += 1
                self.vdof[inode] = vcounter
                self.fdof[inode] = fcounter
            elif self.boundary_conditions[inode] == -1:
                vcounter += 1
                self.vdof[inode] = vcounter
            elif self.boundary_conditions[inode] == 1:
                fcounter += 1
                self.fdof[inode] = fcounter

        self.num_dof = ct.c_int(vcounter*6)

    def lump_masses(self):
        for i_lumped in range(self.n_lumped_mass):
            r = self.lumped_mass_position[i_lumped, :]
            m = self.lumped_mass[i_lumped]
            j = self.lumped_mass_inertia[i_lumped, :, :]

            i_lumped_node = self.lumped_mass_nodes[i_lumped]
            i_lumped_master_elem, i_lumped_master_node_local = self.node_master_elem[i_lumped_node]

            inertia_tensor = np.zeros((6, 6))
            r_skew = algebra.rot_skew(r)
            inertia_tensor[0:3, 0:3] = m*np.eye(3)
            inertia_tensor[0:3, 3:6] = m*np.transpose(r_skew)
            inertia_tensor[3:6, 0:3] = m*r_skew
            inertia_tensor[3:6, 3:6] = j + m*(np.dot(np.transpose(r_skew), r_skew))

            if self.elements[i_lumped_master_elem].rbmass is None:
                # allocate memory
                self.elements[i_lumped_master_elem].rbmass = np.zeros((
                    self.elements[i_lumped_master_elem].max_nodes_elem, 6, 6))

            self.elements[i_lumped_master_elem].rbmass[i_lumped_master_node_local, :, :] += (
                inertia_tensor)

    def generate_master_structure(self):
        self.master = np.zeros((self.num_elem, self.num_node_elem, 2)) - 1
        for i_elem in range(self.num_elem):
            for i_node_local in range(self.elements[i_elem].n_nodes):
                j_elem = 0
                while self.master[i_elem, i_node_local, 0] == -1 and j_elem < i_elem:
                    # for j_node_local in self.elements[j_elem].ordering:
                    for j_node_local in range(self.elements[j_elem].n_nodes):
                        if (self.connectivities[i_elem, i_node_local] ==
                                self.connectivities[j_elem, j_node_local]):
                            self.master[i_elem, i_node_local, :] = [j_elem, j_node_local]
                    j_elem += 1

        self.generate_node_master_elem()

    def add_timestep(self, timestep_info):
        timestep_info.append(StructTimeStepInfo(self.num_node,
                                                self.num_elem,
                                                self.num_node_elem))
        if len(timestep_info) > 1:
            timestep_info[-1] = timestep_info[-2].copy()

        timestep_info[-1].steady_applied_forces = self.ini_info.steady_applied_forces.astype(dtype=ct.c_double,
                                                                                             order='F')

    def next_step(self):
        self.add_timestep(self.timestep_info)

    def generate_node_master_elem(self):
        """
        Returns a matrix indicating the master element for a given node
        :return:
        """
        self.node_master_elem = np.zeros((self.num_node, 2), dtype=ct.c_int, order='F') - 1
        for i_elem in range(self.num_elem):
            for i_node_local in range(self.elements[i_elem].n_nodes):
                if self.master[i_elem, i_node_local, 0] == -1:
                    self.node_master_elem[self.connectivities[i_elem, i_node_local], 0] = i_elem
                    self.node_master_elem[self.connectivities[i_elem, i_node_local], 1] = i_node_local

    def generate_fortran(self):
        # steady, no time-dependant information
        self.fortran['num_nodes'] = np.zeros((self.num_elem,), dtype=ct.c_int, order='F')
        for elem in self.elements:
            self.fortran['num_nodes'][elem.ielem] = elem.n_nodes

        self.fortran['num_mem'] = np.zeros_like(self.fortran['num_nodes'], dtype=ct.c_int)
        for elem in self.elements:
            self.fortran['num_mem'][elem.ielem] = elem.num_mem

        self.fortran['connectivities'] = self.connectivities.astype(ct.c_int, order='F') + 1
        self.fortran['master'] = self.master.astype(dtype=ct.c_int, order='F') + 1
        self.fortran['node_master_elem'] = self.node_master_elem.astype(dtype=ct.c_int, order='F') + 1

        self.fortran['length'] = np.zeros_like(self.fortran['num_nodes'], dtype=ct.c_double, order='F')
        for elem in self.elements:
            self.fortran['length'][elem.ielem] = elem.length

        self.fortran['mass'] = self.mass_db.astype(ct.c_double, order='F')
        self.fortran['stiffness'] = self.stiffness_db.astype(ct.c_double, order='F')
        self.fortran['inv_stiffness'] = self.inv_stiffness_db.astype(ct.c_double, order='F')
        self.fortran['mass_indices'] = self.elem_mass.astype(ct.c_int, order='F') + 1
        self.fortran['stiffness_indices'] = self.elem_stiffness.astype(ct.c_int, order='F') + 1

        self.fortran['frame_of_reference_delta'] = self.frame_of_reference_delta.astype(ct.c_double, order='F')

        self.fortran['vdof'] = self.vdof.astype(ct.c_int, order='F') + 1
        self.fortran['fdof'] = self.fdof.astype(ct.c_int, order='F') + 1

        # self.fortran['steady_applied_forces'] = self.steady_app_forces.astype(dtype=ct.c_double, order='F')

        # undeformed structure matrices
        self.fortran['pos_ini'] = self.ini_info.pos.astype(dtype=ct.c_double, order='F')
        self.fortran['psi_ini'] = self.ini_info.psi.astype(dtype=ct.c_double, order='F')

        max_nodes_elem = self.elements[0].max_nodes_elem
        rbmass_temp = np.zeros((self.num_elem, max_nodes_elem, 6, 6))
        for elem in self.elements:
            for inode in range(elem.n_nodes):
                if elem.rbmass is not None:
                    rbmass_temp[elem.ielem, inode, :, :] = elem.rbmass[inode, :, :]
        self.fortran['rbmass'] = rbmass_temp.astype(dtype=ct.c_double, order='F')

        if self.settings['unsteady']:
            pass
            # TODO
            # if self.dynamic_forces_amplitude is not None:
            #     self.dynamic_forces_amplitude_fortran = self.dynamic_forces_amplitude.astype(dtype=ct.c_double, order='F')
            #     self.dynamic_forces_time_fortran = self.dynamic_forces_time.astype(dtype=ct.c_double, order='F')
            # else:
            #     self.dynamic_forces_amplitude_fortran = np.zeros((self.num_node, 6), dtype=ct.c_double, order='F')
            #     self.dynamic_forces_time_fortran = np.zeros((self.n_tsteps, 1), dtype=ct.c_double, order='F')
            #
            # if self.forced_vel is not None:
            #     self.forced_vel_fortran = self.forced_vel.astype(dtype=ct.c_double, order='F')
            # else:
            #     self.forced_vel_fortran = np.zeros((self.n_tsteps, 6), dtype=ct.c_double, order='F')
            #
            # if self.forced_acc is not None:
            #     self.forced_acc_fortran = self.forced_acc.astype(dtype=ct.c_double, order='F')
            # else:
            #     self.forced_acc_fortran = np.zeros((self.n_tsteps, 6), dtype=ct.c_double, order='F')

    def update_orientation(self, quat, ts=-1):
        self.timestep_info[ts].update_orientation(quat)  # Cga going in here


# ----------------------------------------------------------------------------------------------------------------------

    # def __init_(self, fem_dictionary, dyn_dictionary=None):
        # try:
        #     self.orientation = fem_dictionary['orientation']
        # except KeyError:
        #     self.orientation = None
        #
        # unsteady part
        # if dyn_dictionary is not None:
        #     self.load_unsteady_data(dyn_dictionary)

    def load_unsteady_data(self, dyn_dictionary):
        self.n_tsteps = dyn_dictionary['num_steps']
        try:
            self.dynamic_forces_amplitude = dyn_dictionary['dynamic_forces_amplitude']
            self.dynamic_forces_time = dyn_dictionary['dynamic_forces_time']
        except KeyError:
            self.dynamic_forces_amplitude = None
            self.dynamic_forces_time = None

        try:
            self.forced_vel = dyn_dictionary['forced_vel']
        except KeyError:
            self.forced_vel = None

        try:
            self.forced_acc = dyn_dictionary['forced_acc']
        except KeyError:
            self.forced_acc = None


