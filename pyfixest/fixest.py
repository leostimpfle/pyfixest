import numpy as np
import pandas as pd
from scipy.stats import norm
import pyhdfe
from pyfixest.utils import get_fml_dict
from pyfixest.demean import demean
from formulaic import model_matrix


class Fixest:

    def __init__(self, fml, data):

        self.data = data
        self.var_dict, self.fml_dict = get_fml_dict(fml)

    def demean(self):

        # deparse fxst.fml_dict:
        fixef_keys = list(self.var_dict.keys())
        #fixef_list = [x.split("+") for x in fixef_keys]

        self.demeaned_data_dict = dict()
        for f, fval in enumerate(fixef_keys):
          
            fval_list = fval.split("+")  
            fe = np.array(self.data[fval_list]).astype(int)
            if fe.ndim == 1:
                fe.shape = (len(fe), 1)
            cols = self.var_dict[fval]
            YX = np.array(self.data[cols], dtype = "float64")
            data_demean = pd.DataFrame(demean(YX, fe))
            data_demean.columns = cols
            self.demeaned_data_dict[fval] = data_demean


class Feols:

    def __init__(self, fml, data):

        self.fml = fml
        # if fixef in variable - drop intercept
        Y, X = model_matrix(
              fml,
              data,
              na_action="ignore"
            )
        coefnames = X.columns
        depvars = Y.columns

        Y = np.array(Y, dtype = "float64")
        X = np.array(X, dtype = "float64")
        
        # drop intercept when fe projected out
        X = X[:, coefnames != 'Intercept']
        self.coefnames = coefnames[coefnames != 'Intercept']
        
        self.Y = Y
        self.X = X
        self.N, self.k = X.shape

    def fit(self):
        '''
        regression estimation for a single model
        '''

        self.tXX = np.transpose(self.X) @ self.X
        self.tXXinv = np.linalg.inv(self.tXX)

        self.tXy = (np.transpose(self.X) @ self.Y)
        beta_hat = self.tXXinv @ self.tXy
        self.beta_hat = beta_hat.flatten()
        self.Y_hat = (self.X @ self.beta_hat).reshape((self.N, 1))
        self.u_hat = (self.Y - self.Y_hat)

    def vcov(self, vcov = "hetero"):

        '''
        compute covariance matrices
        '''

        if isinstance(vcov, dict):
            vcov_type_detail = list(vcov.keys())[0]
            self.clustervar = list(vcov.values())[0]
        elif isinstance(vcov, list):
            vcov_type_detail = vcov
        elif isinstance(vcov, str):
            vcov_type_detail = vcov
        else:
            assert False, "arg vcov needs to be a dict, string or list"

        if vcov_type_detail == "iid":
            vcov_type = "iid"
        elif vcov_type_detail in ["hetero", "HC1", "HC2", "HC3"]:
            vcov_type = "hetero"
        elif vcov_type_detail in ["CRV1", "CRV3"]:
            vcov_type = "CRV"


        # compute vcov
        if vcov_type == 'iid':

            self.vcov = (self.tXXinv * np.mean(self.u_hat ** 2))

        elif vcov_type == 'hetero':

            if vcov_type_detail in ["hetero", "HC1"]:
                self.ssc = (self.N / (self.N - self.k))
                u = self.u_hat.flatten()
            elif vcov_type_detail in ["HC2", "HC3"]:
                self.ssc = 1
                leverage = np.mean(self.X * (self.X @ self.tXXinv), axis=1)
                if vcov_type_detail == "HC2":
                     u = (1 - leverage) * self.u_hat.flatten()
                else:
                    u = np.sqrt(1 - leverage) * self.u_hat.flatten()

            meat = np.transpose(self.X) * (u ** 2) @ self.X
            self.vcov = self.ssc * self.tXXinv @ meat @  self.tXXinv

        elif vcov_type == "CRV":

            # if there are missings - delete them!
            cluster_df = np.array(self.data[self.clustervar])
            # drop NAs
            if len(self.na_index) != 0:
                cluster_df = np.delete(cluster_df, 0, self.na_index)

            clustid = np.unique(cluster_df)
            self.G = len(clustid)

            if vcov_type_detail == "CRV1":

                meat = np.zeros((self.k, self.k))

                for igx, g, in enumerate(clustid):

                    Xg = self.X[np.where(cluster_df == g)]
                    ug = self.u_hat[np.where(cluster_df == g)]
                    score_g = (np.transpose(Xg) @ ug).reshape((self.k, 1))
                    meat += np.dot(score_g, score_g.transpose())

                self.ssc = self.G / (self.G - 1) * (self.N-1) / (self.N-self.k)
                self.vcov = self.ssc * self.tXXinv @ meat @ self.tXXinv

            elif vcov_type_detail == "CRV3":

                # check: is fixed effect cluster fixed effect?
                # if not, either error or turn fixefs into dummies
                # for now: don't allow for use with fixed effects
                assert self.has_fixef == False, "CRV3 currently not supported with arbitrary fixed effects"

                beta_jack = np.zeros((self.G, self.k))
                tXX = np.transpose(self.X) @ self.X

                for ixg, g in enumerate(clustid):


                    Xg = self.X[np.where(cluster_df == g)]
                    Yg = self.Y[:, x][np.where(cluster_df == g)]

                    tXgXg = np.transpose(Xg) @ Xg

                    # jackknife regression coefficient
                    beta_jack[ixg, :] = (
                        np.linalg.pinv(
                            tXX - tXgXg) @ (self.tXy - np.transpose(Xg) @ Yg)
                    ).flatten()

                beta_center = self.beta_hat

                vcov = np.zeros((self.k, self.k))
                for ixg, g in enumerate(clustid):
                    beta_centered = beta_jack[ixg, :] - beta_center
                    vcov += np.outer(beta_centered, beta_centered)

                self.ssc = self.G / (self.G - 1)

                self.vcov = self.ssc * vcov

    def inference(self):

        self.se = (
            np.sqrt(np.diagonal(self.vcov))
        )
        self.tstat = (
            self.beta_hat / self.se
        )
        self.pvalue = (
            2*(1-norm.cdf(np.abs(self.tstat)))
        )

    def performance(self):

        self.r_squared = 1 - np.sum(self.u_hat ** 2) / \
            np.sum((self.Y - np.mean(self.Y))**2)
        self.adj_r_squared = (self.N - 1) / (self.N - self.k) * self.r_squared
