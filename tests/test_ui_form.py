# Phase 12 – Step 2: unit tests for the trip form logic (no Streamlit, no network).
import datetime

from agentsville.models import Interest, VacationInfo
from agentsville.samples import sample_vacation_info
from agentsville.ui.form import (
    FieldError,
    TravelerInput,
    TripForm,
    default_form,
    interest_hint,
    to_vacation_info,
    unavailable_interests,
)

D = datetime.date


# Phase 12 – Step 2: a valid form to break one field at a time
def _form(**overrides) -> TripForm:
    values = {
        "travelers": [TravelerInput("Yuri", 30, [Interest.TECHNOLOGY])],
        "date_of_arrival": D(2025, 6, 10),
        "date_of_departure": D(2025, 6, 12),
        "budget": 130,
    }
    values.update(overrides)
    return TripForm(**values)


def _errors(form: TripForm) -> list[str]:
    result = to_vacation_info(form)
    assert isinstance(result, list), f"expected errors, got {result!r}"
    assert all(isinstance(e, FieldError) for e in result)
    return [str(e) for e in result]


def test_default_form_is_the_sample_trip():
    assert to_vacation_info(default_form()) == sample_vacation_info()


def test_valid_form_gives_vacation_info_with_fixed_destination_and_stripped_names():
    result = to_vacation_info(_form(travelers=[TravelerInput("  Yuri ", 30, [Interest.ART])]))
    assert isinstance(result, VacationInfo)
    assert result.destination == "AgentsVille"
    assert result.travelers[0].name == "Yuri"


def test_age_over_limit_names_the_traveler():
    travelers = [
        TravelerInput("Yuri", 30, [Interest.ART]),
        TravelerInput("Hiro", 130, [Interest.ART]),
    ]
    assert _errors(_form(travelers=travelers)) == ["Traveler 2 (Hiro) – age: must be at most 120"]


def test_blank_name_is_required():
    errors = _errors(_form(travelers=[TravelerInput("   ", 30, [Interest.ART])]))
    assert errors == ["Traveler 1 – name: is required"]


def test_no_interests():
    errors = _errors(_form(travelers=[TravelerInput("Yuri", 30, [])]))
    assert errors == ["Traveler 1 (Yuri) – interests: pick at least one interest"]


def test_no_travelers():
    assert _errors(_form(travelers=[])) == ["Travelers: add at least one traveler"]


def test_budget_zero():
    assert _errors(_form(budget=0)) == ["Budget: must be greater than 0"]


def test_departure_before_arrival():
    errors = _errors(_form(date_of_arrival=D(2025, 6, 12), date_of_departure=D(2025, 6, 11)))
    assert errors == ["Dates: departure must be on or after arrival"]


def test_date_error_shown_together_with_field_errors():
    form = _form(budget=0, date_of_arrival=D(2025, 6, 12), date_of_departure=D(2025, 6, 11))
    assert _errors(form) == [
        "Budget: must be greater than 0",
        "Dates: departure must be on or after arrival",
    ]


def test_dates_outside_window():
    errors = _errors(_form(date_of_departure=D(2025, 6, 20)))
    assert len(errors) == 1 and errors[0].startswith("Dates: dates must be between")


def test_theatre_is_never_available():
    assert Interest.THEATRE in unavailable_interests(D(2025, 6, 10), D(2025, 6, 15))


def test_comedy_only_on_june_13():
    assert Interest.COMEDY in unavailable_interests(D(2025, 6, 10), D(2025, 6, 12))
    assert Interest.COMEDY not in unavailable_interests(D(2025, 6, 13), D(2025, 6, 13))


def test_unavailable_interests_with_reversed_dates_is_empty():
    assert unavailable_interests(D(2025, 6, 12), D(2025, 6, 10)) == set()


def test_interest_hint():
    unavailable = {Interest.THEATRE, Interest.COMEDY}
    assert interest_hint([Interest.ART], unavailable) is None
    hint = interest_hint([Interest.THEATRE, Interest.ART, Interest.COMEDY], unavailable)
    assert hint == "No activity for theatre, comedy on these dates."
