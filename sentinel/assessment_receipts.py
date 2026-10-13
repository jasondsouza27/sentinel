"""Stateless, process-local authorization to save an exact reviewed snapshot."""
import base64
import hashlib
import hmac
import json
import math
import time

from .context_harm.integrity import canonical_bytes, canonical_sha256


class SnapshotSigner:
    def __init__(self, secret: bytes, ttl_seconds: int=900, clock=time.time):
        if not isinstance(secret, bytes) or len(secret)<32 or type(ttl_seconds) is not int or ttl_seconds<=0:
            raise ValueError('Invalid snapshot signer configuration')
        self._secret=secret; self.ttl_seconds=ttl_seconds; self.clock=clock

    @staticmethod
    def _encode(value): return base64.urlsafe_b64encode(value).decode('ascii').rstrip('=')

    @staticmethod
    def _decode(value):
        return base64.b64decode(value+'='*((-len(value))%4),altchars=b'-_',validate=True)

    def issue(self, submitted: dict, result: dict) -> str:
        if not isinstance(submitted,dict) or not isinstance(result,dict):
            raise ValueError('Snapshot must contain input and result objects')
        now=self.clock()
        if not math.isfinite(now) or now<0: raise ValueError('Invalid server clock')
        raw=canonical_bytes({'issued_at':int(now),'input_sha256':canonical_sha256(submitted),
                             'result_sha256':canonical_sha256(result)})
        return self._encode(raw)+'.'+self._encode(hmac.digest(self._secret,raw,'sha256'))

    def verify(self, receipt: str, submitted: dict, result: dict) -> None:
        failure='Recheck this content: the assessment receipt is invalid, expired, or from a restarted service.'
        try:
            if not isinstance(receipt,str) or not 1<=len(receipt)<=2048: raise ValueError()
            encoded,signature=receipt.split('.')
            raw=self._decode(encoded); mac=self._decode(signature)
            if not hmac.compare_digest(mac,hmac.digest(self._secret,raw,'sha256')): raise ValueError()
            record=json.loads(raw)
            if set(record)!= {'issued_at','input_sha256','result_sha256'}: raise ValueError()
            issued=record['issued_at']; now=self.clock()
            if type(issued) is not int or not math.isfinite(now) or issued>now or now-issued>self.ttl_seconds:
                raise ValueError()
            if (not isinstance(submitted,dict) or not isinstance(result,dict)
                or not hmac.compare_digest(record['input_sha256'],canonical_sha256(submitted))
                or not hmac.compare_digest(record['result_sha256'],canonical_sha256(result))): raise ValueError()
        except (ValueError,TypeError,KeyError,UnicodeError) as error:
            raise ValueError(failure) from None
