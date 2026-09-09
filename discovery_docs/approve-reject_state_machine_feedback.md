# mason feedback
Hey Hashem, I've got a few questions about your state diagram and schema that my Claude pointed out. I'm not sure if you've given your Claude the handbook as context or not. Have a look whenever you have time but ik your busy so you don't need to respond today:

Schema fields missing:

justification — reason text for Misc spend and the explanation step Amara described
approval_reference — whether advance approval already happened (needed for the £250–£2,000 rule)
attendee_count — headcount for the per-head client entertainment limit
employee_home_office — where the employee's based, decides which meal rule applies (London vs visiting)
journey_duration — trip length, decides allowed rail/air class
State diagram:

Missing a clarification state. Amara said most flags get resolved by her asking the employee one question first, then deciding — right now flagged/high_risk only go straight to approve/reject. "Escalated" doesn't cover this, that's a separate post-rejection step. Can we add an awaiting-clarification loop before the decision?
What is the escalation step and what triggers it?
What's the difference between flagged and high risk?
Also — what's payment_method for? Not seeing where it's sourced from.

# Alex feedback

Just looked over the approval-rejection state diagram, looks really good so far! Here's a few things I was thinking based on the meeting with Amara that could be added:

On the "flagged" path, should we add a path for "awaiting employee response" as Amara described initially going back and forth with the employee for simple issues like missing fields.
We could also add an "auto-reject" path that instantly rejects receipts over a month old, as Amara described this as a policy she would want to see enforced.
This is more clarifying, is duplicate submissions or split-receipting included as high-risk? If so nice, if not we could create paths for those.
Another clarifying, should we also add a "submitter notified via Slack" on the approve path the same as for the rejected path?
[12:52 PM]Other than this though it looks perfect, we can look at it together tomorrow if you'd like?