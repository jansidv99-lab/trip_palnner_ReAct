# Goal
  The "AgentsVille Trip Planner" is a ReAct(THOUGHT → ACTION → OBSERVATION cycle) based application that interacts with an LLM to perform several functions:

## 1.Define Vacation Details
   - Specify the trip duration, interests, and constraints.
   - Use Pydantic to structure and verify this information in a class called VacationInfo.

## 2.Review Weather and Activity schedules
   - Simulate API calls to gather weather data and available activities in bulk
   - Review the data manually to understand the available options

## 3.The ItineraryAgent using ReAct(THOUGHT → ACTION → OBSERVATION cycle)
   - Implement an agent that generates a day-by-day itinerary based on the vacation details
   - The agent will use the tools to refine the plan iteratively, checking the weather and available activities, and ensuring the itinerary meets all constraints.
   -We will implement a agent that generates the itinerary using the ReAct THOUGHT → ACTION → OBSERVATION cycle.
       - The LLM will first generated a THOUGHT / ACTION message, which contains reasoning steps and a tool call invocation.
       - The Python code will parse the tool call and execute it, returning the result as a string to the LLM in an OBSERVATION message.
       - After this cycle repeats n number of times, the LLM will invoke the final_answer_tool to signal to the Python code to end the loop and return the final answer.

## 4.Evaluating the Itinerary
   - Evaluate the itinerary using a set of criteria to ensure a high-quality travel plan
     - does the agent suggest activities that are not suitable for the weather? This specific evaluation function will require the use of an LLM to compare the event description against the weather data.
     - does the itinerary match the city and the dates requested?
     - is the total cost calulation accurate and is it within budget?
     - does the agent hallucinate any activities that are not available?
     - suggest the evals for better valuation

## 5.Defining the Tools
   - We will define tools to assist the agent
    - calculator_tool: to accurately calculate costs
    - get_activities_by_date_tool: to retrieve activities for a specific date
    - run_evals_tool: to evaluate the itinerary against the criteria
    - final_answer_tool: to provide the final answer in a structured format
    - wheatehr tool : to get the weather detalis based on day
    - suggest any additional tools


## 6. UI    

   - Build a Streamlit page where a user enters trip preferences and clicks a button to generate an
AgentsVille itinerary. The UI collects input, validates it into the existing Pydantic models, calls
the itinerary agent, and displays the resulting `TravelPlan`.
   - 

## GCP resource 
   - use the exisitng resources provided project id and region 

## data 
   - always refere data in folder /data   

## 7. CI/CD pipelines

## 8. AI Quality Assurance Platform
 three layers of quality checks

| Layer | Question it answers | Weight |
|---|---|---|
| **A – Deterministic testing** | Does the software work? | minimal |
| **B – Probabilistic evals** | Is the AI producing acceptable outcomes? | **main focus** |
| **C – System metrics & drift monitoring** | Is it sustainable in production? | **main focus** |


## incorporate feedback on the initial itinerary - keep it for next phase development 
    - This agent will also incorporate feedback on the initial itinerary from the travelers to ensure the final plan has at least 2 activities per day. A new evaluation function using a powerful LLM will be created to check this user feedback.
    - The agent will use the tools above to refine the plan iteratively, checking the weather and available activities, and ensuring the itinerary meets all constraints.












