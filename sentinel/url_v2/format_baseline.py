"""Four fixed URL-format indicators, diagnostic only and never deployable."""
from sklearn.base import BaseEstimator,TransformerMixin
from sentinel.url_ml.contracts import DatasetError
from .audit import format_flags

FEATURE_NAMES=["https","www_host","non_root_path","query_present"]

class FormatTransformer(BaseEstimator,TransformerMixin):
    def __init__(self,parser): self.parser=parser
    def fit(self,X,y=None): return self
    def transform(self,X):
        import numpy as np
        return np.asarray([[int(flag in format_flags(self.parser.normalize(url).model_url)) for flag in FEATURE_NAMES] for url in X],dtype=np.float32).reshape(-1,4)
    def get_feature_names_out(self,input_features=None):
        import numpy as np
        return np.asarray(FEATURE_NAMES,dtype=object)

def build_format_pipeline(branch,params,parser):
    if branch!="format_only": raise DatasetError("format_branch_invalid")
    from sklearn.pipeline import Pipeline
    from sklearn.linear_model import LogisticRegression
    from sentinel.url_ml.features import CanonicalTransformer
    return Pipeline([("canonical",CanonicalTransformer(parser)),("format",FormatTransformer(parser)),
      ("classifier",LogisticRegression(C=1,class_weight=None,solver="liblinear",max_iter=1000,random_state=42))])
