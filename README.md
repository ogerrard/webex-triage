# webex-triage

webex-triage is a Python script to enable communication between first responders and on-call doctors.

## Installation

Use the package manager [pip](https://pip.pypa.io/en/stable/) to install requirements.txt.

```bash
pip install -r requirements.txt
```

## Configurations

Create a .env file (using sample.env) to add all necessary keys, tokens and variables for your bot.

```
WEBEX_TEAMS_ACCESS_TOKEN=<BOT TOKEN>
TEAMS_BOT_URL=<SERVER URL>
TEAMS_BOT_EMAIL=<BOT EMAIL>
TEAMS_BOT_APP_NAME=<BOT NAME>
DOCTORS_ROOM=<SHARED DOCTORS ROOM>
DATABASE_NAME=<DATABASE NAME>
```

## Usage

Run the script with [Uvicorn](https://www.uvicorn.org/) using any necessary arguments for your setup. By default it will run using localhost:8000.

``` 
uvicorn main:app 
```

## Contributing
Pull requests are welcome. For major changes, please open an issue first to discuss what you would like to change.


## License
[GPLv3](https://choosealicense.com/licenses/gpl-3.0/)