import unittest

import pandas as pd

from quant.signals.foreign_investor import _call_inquire_investor


class FakeStructuredTool:
    def __init__(self):
        self.kwargs = None

    def invoke(self, kwargs):
        self.kwargs = kwargs
        return pd.DataFrame([{"frgn_ntby_qty": "10"}])


class ForeignInvestorSignalTests(unittest.TestCase):
    def test_inquire_investor_structured_tool_is_invoked_with_kwargs(self):
        tool = FakeStructuredTool()

        df = _call_inquire_investor(tool, env_dv="real", stock_code="005930")

        self.assertEqual(tool.kwargs["env_dv"], "real")
        self.assertEqual(tool.kwargs["fid_cond_mrkt_div_code"], "J")
        self.assertEqual(tool.kwargs["fid_input_iscd"], "005930")
        self.assertEqual(df.iloc[0]["frgn_ntby_qty"], "10")


if __name__ == "__main__":
    unittest.main()
