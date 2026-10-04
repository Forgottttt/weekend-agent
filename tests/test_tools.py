"""检查关键约束，而不只检查代码能否运行。"""

import unittest

from weekend_agent.tools import ToolRegistry, TripTools


class ToolTests(unittest.TestCase):
    def setUp(self):
        self.registry = ToolRegistry(TripTools())

    def check(self, stops, budget=200, group_size=2, registry=None):
        return (registry or self.registry).execute("check_itinerary", {
            "stops": stops, "budget_per_person": budget, "group_size": group_size,
            "start_time": "10:00", "end_time": "18:00",
        })

    def test_search_obeys_all_filters(self):
        result = self.registry.execute("search_places", {
            "city": "杭州", "tags": ["拍照"], "indoor": True, "max_price": 30,
        })
        self.assertTrue(result["ok"])
        self.assertEqual([p["id"] for p in result["data"]["places"]], ["p09"])

    def test_budget_is_per_person_and_group_cost_is_separate(self):
        result = self.check([{"place_id": "p01", "start": "10:00"},
                             {"place_id": "f01", "start": "12:00"}], budget=37, group_size=3)
        self.assertTrue(result["data"]["valid"])
        self.assertEqual(result["data"]["cost_per_person"], 37)
        self.assertEqual(result["data"]["total_group_cost"], 111)

    def test_low_budget_rejects_plan(self):
        result = self.check([{"place_id": "f01", "start": "12:00"}], budget=20)
        self.assertFalse(result["data"]["valid"])
        self.assertIn("预算超出", result["data"]["issues"][0])

    def test_route_requires_enough_time_between_stops(self):
        result = self.check([{"place_id": "p01", "start": "10:00"},
                             {"place_id": "f01", "start": "11:30"}])
        self.assertTrue(any("交通时间不足" in issue for issue in result["data"]["issues"]))

    def test_visit_must_finish_before_closing(self):
        result = self.check([{"place_id": "p09", "start": "16:00"}])
        self.assertTrue(any("营业时段" in issue for issue in result["data"]["issues"]))

    def test_unknown_place_returns_error(self):
        result = self.registry.execute("get_route", {"from_id": "missing", "to_id": "f01"})
        self.assertFalse(result["ok"])

    def test_rain_rejects_outdoor_plan(self):
        rainy = ToolRegistry(TripTools(rain=True))
        result = self.check([{"place_id": "p01", "start": "10:00"}], registry=rainy)
        self.assertFalse(result["data"]["valid"])
        self.assertIn("户外", result["data"]["issues"][0])

    def test_empty_plan_is_not_valid(self):
        self.assertFalse(self.check([])["data"]["valid"])

    def test_meal_requirement_rejects_activity_only_plan(self):
        # 回归：用餐要求必须与雨天一样由应用注入后交给 check_itinerary 判定。
        # 否则工具会给出「假绿灯」，模型要到终审才被拒绝，白烧若干轮。
        with_meal = ToolRegistry(TripTools(include_meal=True))
        result = self.check([{"place_id": "p01", "start": "10:00"}], registry=with_meal)
        self.assertFalse(result["data"]["valid"])
        self.assertTrue(any("用餐" in issue for issue in result["data"]["issues"]))

    def test_meal_requirement_cannot_be_widened_by_tool_arguments(self):
        # 用户级约束不是工具参数：模型传 include_meal 只会被 Schema 拒绝，
        # 因此无法把「要求用餐」放宽成「不用用餐」。
        result = self.registry.execute("check_itinerary", {
            "stops": [{"place_id": "p01", "start": "10:00"}], "budget_per_person": 200,
            "group_size": 2, "start_time": "10:00", "end_time": "18:00", "include_meal": False,
        })
        self.assertFalse(result["ok"])
        self.assertIn("未知字段", result["error"])

    def test_unknown_and_bad_arguments_do_not_execute(self):
        self.assertFalse(self.registry.execute("run_python", {})["ok"])
        self.assertFalse(self.registry.execute("get_weather", {"city": "杭州"})["ok"])
        self.assertFalse(self.registry.execute("search_places", {
            "city": "杭州", "tags": [], "indoor": None, "max_price": float("nan"),
        })["ok"])
        self.assertFalse(self.check([{"place_id": "p01", "start": "25:00"}])["ok"])
        self.assertFalse(self.check([{"place_id": "p01", "start": "10:00"}], group_size=True)["ok"])


if __name__ == "__main__":
    unittest.main()
