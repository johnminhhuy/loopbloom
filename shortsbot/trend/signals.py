"""Extra 'is it rising?' signal from Google Trends (optional; unofficial, may break)."""
from ..util import log


def google_trends(terms):
    """Return {term: ratio} where ratio = last-week interest / first-week interest over ~1 month."""
    try:
        from pytrends.request import TrendReq
    except ImportError:
        log("pytrends not installed - skipping Google Trends (pip install pytrends to enable)")
        return {}
    out = {}
    try:
        pt = TrendReq(hl="en-US", tz=420)
        for i in range(0, len(terms), 5):
            chunk = terms[i:i + 5]
            pt.build_payload(chunk, timeframe="today 1-m")
            df = pt.interest_over_time()
            if df is None or df.empty:
                continue
            for t in chunk:
                if t in df:
                    first, last = df[t].iloc[:7].mean(), df[t].iloc[-7:].mean()
                    out[t] = float(last / first) if first > 0 else (2.0 if last > 0 else 1.0)
    except Exception as e:
        log(f"google trends failed (ignored): {str(e)[:120]}")
    return out
