"""Versioned features derived only from the submitted URL string."""
import string
from urllib.parse import urlsplit
import numpy as np
from sklearn.base import BaseEstimator,TransformerMixin

FEATURE_NAMES=("url_length","host_length","path_length","query_length","host_label_count","dot_count",
               "digit_ratio","letter_ratio","punctuation_ratio","hyphen_count","user_info_count",
               "encoding_count","ip_host","punycode","unknown_suffix","is_https")

def lexical_features(parsed):
    value=parsed.model_url; parts=urlsplit(value); length=max(len(value),1)
    values=(len(value),len(parsed.host),len(parts.path),len(parts.query),len(parsed.host.split(".")),value.count("."),
            sum(c.isdigit() for c in value)/length,sum(c.isalpha() for c in value)/length,
            sum(c in string.punctuation for c in value)/length,value.count("-"),parts.netloc.count("@"),value.count("%"),
            "ip_host" in parsed.flags,"punycode" in parsed.flags,"unknown_suffix" in parsed.flags,parts.scheme=="https")
    return dict(zip(FEATURE_NAMES,map(float,values)))

class CanonicalTransformer(TransformerMixin,BaseEstimator):
    def __init__(self,parser): self.parser=parser
    def fit(self,X,y=None): return self
    def transform(self,X): return [self.parser.normalize(value).model_url for value in X]

class LexicalTransformer(TransformerMixin,BaseEstimator):
    def __init__(self,parser): self.parser=parser
    def fit(self,X,y=None): return self
    def transform(self,X):
        return np.asarray([list(lexical_features(self.parser.normalize(value)).values()) for value in X],dtype=np.float32).reshape(-1,len(FEATURE_NAMES))
    def get_feature_names_out(self,input_features=None): return np.array(FEATURE_NAMES,dtype=object)
