import pytest
import re
import numpy as np
import pandas as pd
from pyfixest.fixest import Fixest
from pyfixest.utils import get_data

# rpy2 imports
from rpy2.robjects.packages import importr
import rpy2.robjects as ro
from rpy2.robjects import pandas2ri

pandas2ri.activate()

fixest = importr("fixest")
stats = importr("stats")

rtol = 1e-05
atol = 1e-05


@pytest.mark.parametrize("N", [100, 1000])
@pytest.mark.parametrize("seed", [879111])
@pytest.mark.parametrize("beta_type", ["1", "2", "3"])
@pytest.mark.parametrize("error_type", ["1", "2", "3"])
@pytest.mark.parametrize("dropna", [False, True])

@pytest.mark.parametrize(
    "fml",
    [
        ("Y~X1"),
        ("Y~X1+X2"),
        ("Y~X1|f2"),
        ("Y~X1|f2+f3"),
        ("Y~X2|f2+f3"),
        ("log(Y) ~ X1"),
        ("Y ~ exp(X1)"),
        ("Y ~ C(f1)"),
        ("Y ~ X1 + C(f1)"),
        ("Y ~ X1 + C(f2)"),
        ("Y ~ X1 + C(f1) + C(f2)"),
        ("Y ~ X1 + C(f1) | f2"),
        ("Y ~ X1 + C(f1) | f2 + f3"),
        # ("Y ~ X1 + C(f1):C(fe2)"),
        # ("Y ~ X1 + C(f1):C(fe2) | f3"),
        ("Y~X1|f2^f3"),
        ("Y~X1|f1 + f2^f3"),  # this one fails
        ("Y~X1|f2^f3^f1"),  # this one fails
        ("Y ~ X1:X2"),
        ("Y ~ X1:X2 | f3"),
        ("Y ~ X1:X2 | f3 + f1"),
        ("log(Y) ~ X1:X2 | f3 + f1"),
        ("log(Y) ~ log(X1):X2 | f3 + f1"),
        ("Y ~  X2 + exp(X1) | f3 + f1"),
        ("Y ~ i(f1,X2)"),
        ("Y ~ i(f2,X2)"),
        ("Y ~ i(f1,X2) | f2"),
        ("Y ~ i(f1,X2) | f2 + f3"),
        #("Y ~ i(f1,X2, ref='1.0')"),
        #("Y ~ i(f2,X2, ref='2.0')"),
        #("Y ~ i(f1,X2, ref='3.0') | f2"),
        #("Y ~ i(f1,X2, ref='4.0') | f2 + f3"),
        ("Y ~ C(f1)"),
        ("Y ~ C(f1) + C(f2)"),
        #("Y ~ C(f1):X2"),
        #("Y ~ C(f1):C(f2)"),
        ("Y ~ C(f1) | f2"),

        ("Y ~ I(X1 ** 2)"),
        ("Y ~ I(X1 ** 2) + I(X2**4)"),
        ("Y ~ X1*X2"),
        ("Y ~ X1*X2 | f1+f2"),
        #("Y ~ X1/X2"),
        #("Y ~ X1/X2 | f1+f2"),

        #("Y ~ X1 + poly(X2, 2) | f1"),  # bug in formulaic in case of NAs in X1, X2

        # IV starts here
        ("Y ~ 1 | X1 ~ Z1"),
        "Y ~  X2 | X1 ~ Z1",
        "Y ~ X2 + C(f1) | X1 ~ Z1",
        "Y2 ~ 1 | X1 ~ Z1",
        "Y2 ~ X2 | X1 ~ Z1",
        "Y2 ~ X2 + C(f1) | X1 ~ Z1",
        "log(Y) ~ 1 | X1 ~ Z1",
        "log(Y) ~ X2 | X1 ~ Z1",
        "log(Y) ~ X2 + C(f1) | X1 ~ Z1",
        "Y ~ 1 | f1 | X1 ~ Z1",
        "Y ~ 1 | f1 + f2 | X1 ~ Z1",
        "Y ~ 1 | f1^f2 | X1 ~ Z1",
        "Y ~  X2| f1 | X1 ~ Z1",
        # tests of overidentified models
        "Y ~ 1 | X1 ~ Z1 + Z2",
        "Y ~ X2 | X1 ~ Z1 + Z2",
        "Y ~ X2 + C(f1) | X1 ~ Z1 + Z2",
        "Y ~ 1 | f1 | X1 ~ Z1 + Z2",
        "Y2 ~ 1 | f1 + f2 | X1 ~ Z1 + Z2",
        "Y2 ~  X2| f2 | X1 ~ Z1 + Z2",

    ],
)
def test_single_fit(N, seed, beta_type, error_type, dropna, fml):
    """
    test pyfixest against fixest via rpy2

        - for multiple models
        - and multiple inference types
        - ... compare regression coefficients and standard errors
        - tba: t-statistics, covariance matrices, other metrics
    """

    data = get_data(N=N, seed=seed, beta_type=beta_type, error_type=error_type)
    # long story, but categories need to be strings to be converted to R factors,
    # this then produces 'nan' values in the pd.DataFrame ...
    data[data == "nan"] = np.nan

    if dropna:
        data = data.dropna()


    vars = fml.split("~")[1].split("|")[0].split("+")

    # small intermezzo, as rpy2 does not drop NAs from factors automatically
    # note that fixes does this correctly
    # this currently does not yet work for C() interactions
    factor_vars = []
    for var in vars:
        if "C(" in var:
            var = var.replace(" ", "")
            var = var[2:-1]
            factor_vars.append(var)

    # if factor_vars is not empty
    if factor_vars:
        data_r = data[~data[factor_vars].isna().any(axis=1)]
    else:
        data_r = data

    # suppress correction for fixed effects
    # fixest.setFixest_ssc(fixest.ssc(True, "nested", True, "min", "min", False))

    r_fml = _c_to_as_factor(fml)

    # iid errors
    try:
        pyfixest = Fixest(data=data).feols(fml, vcov="iid")
    except ValueError as e:
        if "is not of type 'O' or 'category'" in str(e):
            data["f1"] = pd.Categorical(data.f1.astype(str))
            data["f2"] = pd.Categorical(data.f2.astype(str))
            data["f3"] = pd.Categorical(data.f3.astype(str))
            pyfixest = Fixest(data=data).feols(fml, vcov="iid")
        else:
            raise ValueError("Code fails with an uninformative error message.")

    py_coef = pyfixest.coef().values
    py_se = pyfixest.se().values
    py_pval = pyfixest.pvalue().values
    py_tstat = pyfixest.tstat().values
    py_confint = pyfixest.confint().values.flatten()

    # write list comprehension that sorts py_coef py_ses etc with np.sort
    py_coef, py_se, py_pval, py_tstat, py_confint = [np.sort(x) for x in [py_coef, py_se, py_pval, py_tstat, py_confint]]

    r_fixest = fixest.feols(
        ro.Formula(r_fml),
        se="iid",
        data=data_r,
        ssc=fixest.ssc(True, "none", True, "min", "min", False),
    )

    r_coef = stats.coef(r_fixest)
    r_se = fixest.se(r_fixest)
    r_pval = fixest.pvalue(r_fixest)
    r_tstat = fixest.tstat(r_fixest)
    r_confint = np.array(stats.confint(r_fixest)).flatten()

    # write list comprehension that sorts py_coef py_ses etc with np.sort
    r_coef, r_se, r_pval, r_tstat, r_confint = [np.sort(x) for x in [r_coef, r_se, r_pval, r_tstat, r_confint]]

    np.testing.assert_allclose(
        py_coef,
        r_coef,
        rtol = rtol,
        atol = atol,
        err_msg = "py_coef != r_coef"
    )

    np.testing.assert_allclose(
        py_se,
        r_se,
        rtol = rtol,
        atol = atol,
        err_msg = "py_se != r_se for iid errors"
    )

    np.testing.assert_allclose(
        py_pval,
        r_pval,
        rtol = rtol,
        atol = atol,
        err_msg = "py_pval != r_pval for iid errors"
    )

    np.testing.assert_allclose(
        py_tstat,
        r_tstat,
        rtol = rtol,
        atol = atol,
        err_msg = "py_tstat != r_tstat for iid errors"
    )

    np.testing.assert_allclose(
        py_confint,
        r_confint,
        rtol = rtol,
        atol = atol,
        err_msg = "py_confint != r_confint for iid errors"
    )


    # heteroskedastic errors
    pyfixest.vcov("HC1")

    py_se = pyfixest.se().values
    py_pval = pyfixest.pvalue().values
    py_tstat = pyfixest.tstat().values
    py_confint = pyfixest.confint().values.flatten()

    # sort
    py_se, py_pval, py_tstat, py_confint = [np.sort(x) for x in [py_se, py_pval, py_tstat, py_confint]]

    r_fixest = fixest.feols(
        ro.Formula(r_fml),
        se="hetero",
        data=data_r,
        ssc=fixest.ssc(True, "none", True, "min", "min", False),
    )

    r_se = fixest.se(r_fixest)
    r_pval = fixest.pvalue(r_fixest)
    r_tstat = fixest.tstat(r_fixest)
    r_confint = np.array(stats.confint(r_fixest)).flatten()

    # sort
    r_se, r_pval, r_tstat, r_confint = [np.sort(x) for x in [r_se, r_pval, r_tstat, r_confint]]

    np.testing.assert_allclose(
        py_se,
        r_se,
        rtol = rtol,
        atol = atol,
        err_msg = "py_se != r_se for heteroskedastic errors"
    )

    np.testing.assert_allclose(
        py_pval,
        r_pval,
        rtol = rtol,
        atol = atol,
        err_msg = "py_pval != r_pval for heteroskedastic errors"
    )

    np.testing.assert_allclose(
        py_tstat,
        r_tstat,
        rtol = rtol,
        atol = atol,
        err_msg = "py_tstat != r_tstat for heteroskedastic errors"
    )

    np.testing.assert_allclose(
        py_confint,
        r_confint,
        rtol = rtol,
        atol = atol,
        err_msg = "py_confint != r_confint for heteroskedastic errors"
    )


    # cluster robust errors
    pyfixest.vcov({"CRV1": "group_id"})

    py_se = pyfixest.se().values
    py_pval = pyfixest.pvalue().values
    py_tstat = pyfixest.tstat().values
    py_confint = pyfixest.confint().values.flatten()

    # sort
    py_se, py_pval, py_tstat, py_confint = [np.sort(x) for x in [py_se, py_pval, py_tstat, py_confint]]

    r_fixest = fixest.feols(
        ro.Formula(r_fml),
        cluster=ro.Formula("~group_id"),
        data=data_r,
        ssc=fixest.ssc(True, "none", True, "min", "min", False),
    )

    r_se = fixest.se(r_fixest)
    r_pval = fixest.pvalue(r_fixest)
    r_tstat = fixest.tstat(r_fixest)
    r_confint = np.array(stats.confint(r_fixest)).flatten()

    # sort
    r_se, r_pval, r_tstat, r_confint = [np.sort(x) for x in [r_se, r_pval, r_tstat, r_confint]]

    np.testing.assert_allclose(
        py_se,
        r_se,
        rtol = rtol,
        atol = atol,
        err_msg = "py_se != r_se for cluster robust errors"
    )

    np.testing.assert_allclose(
        py_pval,
        r_pval,
        rtol = rtol,
        atol = atol,
        err_msg = "py_pval != r_pval for cluster robust errors"
    )

    np.testing.assert_allclose(
        py_tstat,
        r_tstat,
        rtol = rtol,
        atol = atol,
        err_msg = "py_tstat != r_tstat for cluster robust errors"
    )

    np.testing.assert_allclose(
        py_confint,
        r_confint,
        rtol = rtol,
        atol = atol,
        err_msg = "py_confint != r_confint for cluster robust errors"
    )


@pytest.mark.parametrize("N", [100, 1000])
@pytest.mark.parametrize("seed", [17021])
@pytest.mark.parametrize("beta_type", ["1", "2", "3"])
@pytest.mark.parametrize("error_type", ["1", "2", "3"])
@pytest.mark.parametrize("dropna", [False, True])

@pytest.mark.parametrize(
    "fml_multi",
    [
        ("Y + Y2 ~X1"),
        ("Y + log(Y2) ~X1+X2"),
        ("Y + Y2 ~X1|f1"),
        ("Y + Y2 ~X1|f1+f2"),
        ("Y + Y2 ~X2|f2+f3"),
        ("Y + Y2 ~ sw(X1, X2)"),
        ("Y + Y2 ~ sw(X1, X2) |f1 "),
        ("Y + Y2 ~ csw(X1, X2)"),
        ("Y + Y2 ~ csw(X1, X2) | f2"),
        ("Y + Y2 ~ I(X1**2) + csw(f1,f2)"),
        ("Y + Y2 ~ X1 + csw(f1, f2) | f3"),
        ("Y + Y2 ~ X1 + csw0(X2, f3)"),
        ("Y + Y2 ~ X1 + csw0(f1, f2) | f3"),
        ("Y + Y2 ~ X1 | csw0(f1,f2)"),
        ("Y + log(Y2) ~ sw(X1, X2) | csw0(f1,f2,f3)"),
        ("Y ~ C(f2):X2 + sw0(X1, f3)"),

        #("Y ~ i(f1,X2) | csw0(f2)"),
        #("Y ~ i(f1,X2) | sw0(f2)"),
        #("Y ~ i(f1,X2) | csw(f2, f3)"),
        #("Y ~ i(f1,X2) | sw(f2, f3)"),

        #("Y ~ i(f1,X2, ref = -5) | sw(f2, f3)"),
        #("Y ~ i(f1,X2, ref = -8) | csw(f2, f3)"),
    ],
)
def test_multi_fit(N, seed, beta_type, error_type, dropna, fml_multi):
    """
    test pyfixest against fixest_multi objects
    """

    data = get_data(N=N, seed=seed, beta_type=beta_type, error_type=error_type)
    data[data == "nan"] = np.nan

    if dropna:
        data = data.dropna()

    # suppress correction for fixed effects
    fixest.setFixest_ssc(fixest.ssc(True, "none", True, "min", "min", False))

    r_fml = _py_fml_to_r_fml(fml_multi)

    try:
        pyfixest = Fixest(data=data).feols(fml_multi)
    except ValueError as e:
        if "is not of type 'O' or 'category'" in str(e):
            data["f1"] = pd.Categorical(data.f1.astype(str))
            data["f2"] = pd.Categorical(data.f2.astype(str))
            data["f3"] = pd.Categorical(data.f3.astype(str))
            data[data == "nan"] = np.nan
            pyfixest = Fixest(data=data).feols(fml_multi)
        else:
            raise ValueError("Code fails with an uninformative error message.")

    r_fixest = fixest.feols(
        ro.Formula(r_fml),
        data=data,
        ssc=fixest.ssc(True, "none", True, "min", "min", False)
    )

    for x, _ in range(0):

        mod = pyfixest.fetch_model(x)
        py_coef = mod.coef().values
        py_se = mod.se().values

        # sort py_coef, py_se
        py_coef, py_se = [np.sort(x) for x in [py_coef, py_se]]

        fixest_object = r_fixest.rx2(x+1)
        fixest_coef = fixest_object.rx2("coefficients")
        fixest_se = fixest_object.rx2("se")

        #fixest_coef = stats.coef(r_fixest)
        #fixest_se = fixest.se(r_fixest)

        # sort fixest_coef, fixest_se
        fixest_coef, fixest_se = [np.sort(x) for x in [fixest_coef, fixest_se]]

        np.testing.assert_allclose(
            py_coef,
            fixest_coef,
            rtol = rtol,
            atol = atol,
            err_msg = "Coefs are not equal."
        )
        np.testing.assert_allclose(
            py_se,
            fixest_se,
            rtol = rtol,
            atol = atol,
            err_msg = "SEs are not equal."
        )



def _py_fml_to_r_fml(py_fml):
    """
    pyfixest multiple estimation fml syntax to fixest multiple depvar
    syntax converter,
    i.e. 'Y1 + X2 ~ X' -> 'c(Y1, Y2) ~ X'
    """

    py_fml = py_fml.replace(" ", "").replace("C(", "as.factor(")

    fml2 = py_fml.split("|")

    fml_split = fml2[0].split("~")
    depvars = fml_split[0]
    depvars = "c(" + ",".join(depvars.split("+")) + ")"

    if len(fml2) == 1:
        return depvars + "~" + fml_split[1]
    elif len(fml2) == 2:
        return depvars + "~" + fml_split[1] + "|" + fml2[1]
    else:
        return depvars + "~" + fml_split[1] + "|" + "|".join(fml2[1:])


def _c_to_as_factor(py_fml):
    """
    transform formulaic C-syntax for categorical variables into R's as.factor
    """
    # Define a regular expression pattern to match "C(variable)"
    pattern = r"C\((.*?)\)"

    # Define the replacement string
    replacement = r"factor(\1, exclude = NA)"

    # Use re.sub() to perform the replacement
    r_fml = re.sub(pattern, replacement, py_fml)

    return r_fml
