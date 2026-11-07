import random

def unfiltered_jobs(plan):
    return not (plan.keyword or plan.text_query or plan.region or plan.skills or plan.regions or plan.roles or plan.owned_skills or plan.required_skills or plan.preferred_skills or plan.career.levels or plan.career.max_years is not None)

def shuffle_browse(rows,plan):
    if unfiltered_jobs(plan):
        random.SystemRandom().shuffle(rows)
    return rows
