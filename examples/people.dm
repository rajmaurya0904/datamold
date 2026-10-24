# people mapping
@filter status == active
id: int            <- user_id
name               <- first_name, last_name | trim | join(" ") | title
email              <- Email | lower
address.city       <- city
tags[]             <- tags | split(";")
joined             <- signup | date("%Y-%m-%d", "%d %b %Y")
spend: float       <- spend | default(0)
