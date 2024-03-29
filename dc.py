class init_problem_from_model():

    def __init__(self, y, D, h, p=3, C=10):

        self.y = y
        self.n = len(y)

        self.p = p  # number of domains
        self.C = C  # number of classes
        self.U = 1.0 / self.n  # unif dist
        self.eta = 0.01

        self.D = D
        self.h = h

        # Calculate the upper bound.
        self.load_M()

        # compute H
        self.H = np.zeros(self.n)
        for i in range(self.n):
            self.H[i] = (1.0 / self.p) * h[i, :].sum()

        self.verify_D()

    def verify_D(self):
      for k in range(self.p):
        self.D[..., k] = self.D[..., k] / np.sum(self.D[..., k])

    def load_M(self):
        M = 0
        for k in range(self.p):
            tmp = self.y - self.h[..., k]
            tmp = tmp*tmp
            M = max(M, tmp.max())
        self.M = M

    def get_marginal_density(self):
        return self.D

    def get_regressor(self):
        return self.h

    def get_true_values(self):
        return self.y

    def get_H(self):
        return self.H


import numpy as np
def euclidean_proj_simplex(v, s=1):
    """ Compute the Euclidean projection on a positive simplex
    Solves the optimisation problem (using the algorithm from [1]):
        min_w 0.5 * || w - v ||_2^2 , s.t. \sum_i w_i = s, w_i >= 0
    Parameters
    ----------
    v: (n,) numpy array,
       n-dimensional vector to project
    s: int, optional, default: 1,
       radius of the simplex
    Returns
    -------
    w: (n,) numpy array,
       Euclidean projection of v on the simplex
    Notes
    -----
    The complexity of this algorithm is in O(n log(n)) as it involves sorting v.
    Better alternatives exist for high-dimensional sparse vectors (cf. [1])
    However, this implementation still easily scales to millions of dimensions.
    References
    ----------
    [1] Efficient Projections onto the .1-Ball for Learning in High Dimensions
        John Duchi, Shai Shalev-Shwartz, Yoram Singer, and Tushar Chandra.
        International Conference on Machine Learning (ICML 2008)
        http://www.cs.berkeley.edu/~jduchi/projects/DuchiSiShCh08.pdf
    """
    assert s > 0, "Radius s must be strictly positive (%d <= 0)" % s
    n, = v.shape  # will raise ValueError if v is not 1-D
    # check if we are already on the simplex
    if v.sum() == s and np.alltrue(v >= 0):
        # best projection: itself!
        return v
    # get the array of cumulative sums of a sorted (decreasing) copy of v
    u = np.sort(v)[::-1]
    cssv = np.cumsum(u)
    # get the number of > 0 components of the optimal solution
    rho = np.nonzero(u * np.arange(1, n+1) > (cssv - s))[0][-1]
    # compute the Lagrange multiplier associated to the simplex constraint
    theta = (cssv[rho] - s) / (rho + 1.0)
    # compute the projection by thresholding v using theta
    w = (v - theta).clip(min=0)
    return w


class ConvexConcaveSolver():

    def __init__(self, problem, seed, init_z="err", max_iter=100):
        self.problem = problem
        self.seed = seed
        self.max_iter = max_iter
        self.init_z = init_z

    def choose_init_z(self, n=100):
        np.random.seed(self.seed)
        z_vals = np.random.rand(self.problem.p, n)
        o_vals = np.zeros(n)
        for i in range(n):
            z_vals[:, i] /= z_vals[:, i].sum()
            if np.abs(z_vals[:, i].sum() - 1) > 1e-4:
                o_vals[i] = np.inf
            else:
                if self.init_z == "err":
                    tmp = self.problem.compute_err(z_vals[:, i])
                    if len(tmp.shape) == 2:
                        o_vals[i] = max(tmp.sum(axis=-1))
                    else:
                        o_vals[i] = max(tmp)
                elif self.init_z == "obj":
                    o_vals[i] = max(self.problem.compute_obj(z_vals[:, i]))
        # Find initial value which minimizes objective
        k = np.argmin(o_vals)
        if np.abs(z_vals[:, k].sum() - 1) > 1e-8:
            print('somehow returning non norm z0', z_vals[:, k].sum() - 1, o_vals[k])
        return z_vals[:, k]

    def print_iter(self, it, obj, err=None, sub_iter=False, disp=True):
        if disp:
            s = 'Iter {:d}: obj val={:0.4g}'.format(it, obj)
            if not (err is None):
                s += '  err val={:0.4g}'.format(err)
            if sub_iter:
                s = '\t' + s
            print(s)

    def print_obj_increase(self, obj, delta, sub_iter=False, disp=True):
        if disp:
            s = 'Overshot obj ({:0.2g}): lowering delta ({:0.2g})'.format(obj, delta)
            if sub_iter:
                s = '\t' + s
            print(s)

    def check_converged(self, obj, obj_prev, sub_iter=False, disp=True):
        thresh = obj * 1e-8
        o_change = np.abs(obj - obj_prev)
        converged = False
        if o_change < thresh:
            s = 'Converged: change in values less than threshold ({:0.6g})'.format(o_change)
            converged = True
        elif obj < thresh:
            converged = True
            s = 'Converged: objective is less than threshold ({:0.4g})'.format(obj)

        if converged and disp:
            if sub_iter:
                s = '\t' + s
            print(s)

        return converged

    def solve_convex_iter(self, zt, delta=1, max_iter=100, disp=False):
        g_obj = self.problem.compute_obj(zt)
        k = np.argmax(g_obj)

        vt = self.problem.compute_concave(zt)
        gvt = self.problem.compute_grad_concave(zt)
        z = zt.copy();
        last_change = 0

        o_iter = np.zeros(max_iter + 1)
        o_iter[0] = self.problem.compute_linearized_obj(zt, zt, vt, gvt)[k]
        self.print_iter(0, o_iter[0], sub_iter=True, disp=disp)
        for it in range(1, max_iter + 1):
            z_prev = z.copy()
            z = self.update_z(k, z, gvt, delta)
            oi = self.problem.compute_linearized_obj(z_prev, z, vt, gvt)
            o_iter[it] = oi[k]

            change = True
            if o_iter[it] > o_iter[it - 1] or o_iter[it] < 0:
                z = z_prev.copy()
                delta = 0.1 * delta
                self.print_obj_increase(o_iter[it], delta, sub_iter=True, disp=disp)
                o_iter[it] = o_iter[it - 1]
                change = False
            elif self.check_converged(o_iter[it], o_iter[it - 1], sub_iter=True, disp=disp):
                # print 'zdiff', z - z_prev
                break

            if change:
                last_change = it
            if it - last_change > 5:  # no movement after 5 drops in delta
                break

            self.print_iter(it, o_iter[it], sub_iter=True, disp=disp)

        return z

    def update_z(self, k, z, gvt, delta):
        z_grad = self.problem.linearized_obj_gradient(z, gvt)
        scale = 1.0  # 1e-4 /np.abs(z_grad[k,:]).max()
        z -= delta * scale * np.array(z_grad[k, :]).flatten()
        return euclidean_proj_simplex(z)
        # return self.project_onto_simplex(z)

    def project_onto_simplex(self, z):
        z[z < 0] = 0
        return z / z.sum()

    def compute_err_obj(self, z):
        err = self.problem.compute_sq_err(z)
        obj = max(self.problem.compute_obj(z))
        return err, obj

    def solve(self, z0=None, step=None, delta=1e-4):
        p = self.problem.p
        if step is None:
            N = self.max_iter
        else:
            N = step
        if z0 is None:
            z0 = self.choose_init_z(n=100)

        if np.abs(z0.sum() - 1) > 1e-8:
            print('solve non norm z0', z_vals[:, k].sum() - 1, o_vals[k])

        o_iter = np.zeros(N + 1)
        z_iter = np.zeros([p, N + 1])
        err_iter = np.zeros(N + 1)
        err_iter[0], o_iter[0] = self.compute_err_obj(z0)
        z_iter[:, 0] = z0

        self.print_iter(0, o_iter[0], err=err_iter[0])
        DI = N / 10  # display 10 times
        for it in range(1, N + 1):
            z_iter[:, it] = self.solve_convex_iter(z_iter[:, it - 1], delta=delta, disp=False)
            err_iter[it], o_iter[it] = self.compute_err_obj(z_iter[:, it])
            self.print_iter(it, o_iter[it], err=err_iter[it], disp=(it % DI == 0))

            if o_iter[it - 1] < o_iter[it]:
                z_iter[:, it] = z_iter[:, it - 1].copy()
                err_iter[it], o_iter[it] = err_iter[it - 1], o_iter[it - 1]
                delta = 0.5 * delta
                print('\t\t lowering delta to {:0.4g}'.format(delta))
            elif self.check_converged(o_iter[it], o_iter[it - 1]):
                break

        print('Learned z', z_iter[:, it])
        print('Final Obj={:0.4g}'.format(o_iter[it]))
        print('')
        return z_iter[:, it], o_iter[it], err_iter[it]


class ConvexConcaveProblem(object):

    def __init__(self, DP):
        self.D = DP.get_marginal_density()
        # normalize densities per example
        sc = self.D.sum(axis=1)
        # self.D = (self.D+ 1.0/DP.p*1e-250) / (np.tile(sc[:,np.newaxis],[1,DP.p])+1e-250)
        self.D = self.D / sc.max()
        self.U = DP.U / sc.max()
        self.h = DP.get_regressor()
        self.y = DP.get_true_values()
        self.etaU = DP.eta * self.U
        self.M = DP.M
        self.p = DP.p
        self.H = 1.0 / DP.p * self.h.sum(axis=1)
        self.C = DP.C

    def compute_convex(self, z):
        """This is u formulation in our code."""
        Dz, Jz, Kz, hz = self.compute_DzJzKzhz(z)
        err = (hz - self.y) ** 2
        v0 = err - 2 * self.M * np.log(Kz)

        u = np.zeros(self.p)
        for k in range(self.p):
            u[k] = ((self.D[..., k] + self.etaU) * v0).sum()

        return u

    def compute_concave(self, z):
        Dz, Jz, Kz, hz = self.compute_DzJzKzhz(z)
        err = (hz - self.y) ** 2

        EUlogKz = self.etaU * (np.log(Kz)).sum()
        LDzetaU = ((Dz + self.etaU) * err).sum()
        f = LDzetaU - 2 * EUlogKz
        v = np.zeros(self.p)
        for k in range(self.p):
            EDklogKz = (self.D[..., k] * np.log(Kz)).sum()
            gk = -2 * self.M * EDklogKz
            v[k] = gk + f
        return v


    def compute_DzJzKzhz(self,z):
        """
        Assumes D and h have domain index in last place.
        Either D = Dx \in [N,p] or D = Dxy \in [C,N,p]
        Where N=numpts, p=numdomains, C=numCls
        """
        if len(self.h.shape) == 2:
            num_classes = self.C
            hz_prob = np.zeros((len(self.h), num_classes))
            Jz_prob = np.zeros((len(self.h), num_classes))

            z_mat = np.tile(z.flatten(), [self.D.shape[0], 1])
            zD = z_mat * self.D
            Dz = (z_mat * self.D)
            Jz = (zD + self.etaU / self.p)
            Kz = Dz + self.etaU
            hz = Jz / Kz

            for k in range(self.p):
                for x in range(len(self.y)):
                    hz_prob[x, int(self.h[x, k])] += hz[x, k]
                    Jz_prob[x, int(self.h[x, k])] += Jz[x, k]

            # print(hz_prob[:20,:])
            hz = np.argmax(hz_prob, axis=1)
            Jz = np.argmax(Jz_prob, axis=1)
            Dz = (z_mat * self.D).sum(axis=-1)
            Kz = Dz + self.etaU
        else:
            Dh = self.D*self.h
            z_mat = np.tile(z.flatten(), [self.D.shape[0], self.D.shape[1], 1])
            zDh = z_mat*Dh
            Dz = (z_mat * self.D).sum(axis=-1)
            Jz = (zDh + self.etaU/self.p * self.h).sum(axis=-1)
            Kz = Dz + self.etaU
            hz = Jz / Kz

        return Dz,Jz,Kz,hz

    def compute_grad_convex(self, z):
        Dz, Jz, Kz, hz = self.compute_DzJzKzhz(z)
        Dh = self.D * self.h

        gu = np.zeros([self.p, self.p])
        for k in range(self.p):
            a = 2 * (self.D[..., k] + self.etaU) / Kz
            for i in range(self.p):
                v0 = (hz - self.y) * Dh[..., i]
                v1 = ((hz - self.y) * hz + self.M) * self.D[..., i]
                gu[k, i] = (a * (v0 - v1)).sum()

        return np.matrix(gu)

    def compute_grad_concave(self, z):
        Dz, Jz, Kz, hz = self.compute_DzJzKzhz(z)
        Dh = self.D * self.h

        gv = np.zeros([self.p, self.p])
        for k in range(self.p):
            a0 = hz - self.y
            a1 = 2 * self.M * (self.D[..., k] + self.etaU) / Kz
            a2 = a0 ** 2 - 2 * hz * a0 - a1
            for i in range(self.p):
                gv[k, i] = (a2 * self.D[..., i] + 2 * a0 * Dh[..., i]).sum()

        return np.matrix(gv)

    def compute_sq_err(self, z, ind=None):
        Dz, Jz, Kz, hz = self.compute_DzJzKzhz(z)
        if ind is None:
            ind = np.array(range(len(hz)), dtype=int)
        return ((hz[ind] - self.y[ind]) ** 2).sum() / len(ind)

    def compute_err(self, z):
        Dz, Jz, Kz, hz = self.compute_DzJzKzhz(z)
        err = (hz - self.y) ** 2
        # print("error: ", sum(err))
        return err

    def compute_obj(self, z):
        u = self.compute_convex(z)
        v = self.compute_concave(z)
        return u - v

    def obj_gradient(self, z):
        gu = self.compute_grad_convex(z)
        gv = self.compute_grad_concave(z)
        return gu - gv

    def compute_linearized_obj(self, z0, z, v0, gv0):
        u = self.compute_convex(z)
        a0 = gv0 * (z - z0)[:, np.newaxis]
        return (u - v0)[:, np.newaxis] - np.array(a0)

    def linearized_obj_gradient(self, z, gv0):
        gu = self.compute_grad_convex(z)
        return gu - gv0


class ConvexConcaveProblemByClass(ConvexConcaveProblem):

    def __init__(self, D, h, y, eta=1e-20):
        self.D = D
        self.U = 1e-2 * D.mean()
        self.h = h
        self.y = y
        self.etaU = eta * self.U
        self.M = h.max() ** 2
        self.p = h.shape[-1]
        self.H = 1.0 / self.p * self.h.sum(axis=-1)  # TODO: may need to sum over class too??

    def compute_sq_err_percls(self, z, ind=None):
        Dz, Jz, Kz, hz = self.compute_DzJzKzhz(z)
        if ind is None:
            ind = np.array(range(hz.shape[1]), dtype=int)

        return ((hz[:, ind] - self.y[:, ind]) ** 2).sum(axis=1) / len(ind)

    def compute_sq_err(self, z, ind=None):
        err_cls = self.compute_sq_err_percls(z, ind=ind)
        return err_cls.sum()