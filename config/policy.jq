# Stalwart 1.x declarative deployment. Output is NDJSON for `stalwart-cli apply`.
def expr($s): {"else": $s};
def update($o; $v): {"@type":"update",object:$o,value:$v};
def upsert($o; $m; $v): {"@type":"upsert",object:$o,matchOn:$m,value:$v};
def reconcile($o; $m; $v): {"@type":"reconcile",object:$o,matchOn:$m,value:$v};
def listener($name; $port; $proto; $proxy):
  {name:$name,bind:{("0.0.0.0:" + ($port|tostring)):true},protocol:$proto,
   useTls:true,implicitTls:true,tlsTimeout:10000,maxConnections:128,
   overrideProxyTrustedNetworks:$proxy};

upsert("Domain"; ["name"]; {domain:{name:"tmail.internal",enable:true,
  aliases:{},allowRelaying:false,catchAllAddress:null,reportAddressUri:null,
  subAddressing:{"@type":"Disabled"},certificateManagement:{"@type":"Manual"},
  dkimManagement:{"@type":"Manual"},dnsManagement:{"@type":"Manual"}}}),
upsert("Role"; ["description"]; {
  mailRole:{description:"tmail mailbox",enabledPermissions:$mailPermissions[0],disabledPermissions:{},roleIds:{}},
  adminRole:{description:"tmail administrator",enabledPermissions:$adminPermissions[0],disabledPermissions:{},roleIds:{}},
  maintenanceRole:{description:"tmail certificate reload",enabledPermissions:{
    authenticate:true,sysActionCreate:true,actionReloadTlsCertificates:true},disabledPermissions:{},roleIds:{}}
}),
update("Authentication"; {defaultUserRoleIds:{"#mailRole":true},defaultAdminRoleIds:{"#adminRole":true},
  defaultGroupRoleIds:{},minPasswordLength:16,minPasswordStrength:"three",passwordHashAlgorithm:"argon2id"}),
upsert("SymmetricKey"; ["description"]; {blobKey:{description:"tmail blob encryption",cipher:"aes256Gcm",
  key:{"@type":"File",filePath:"/run/secrets/blob_key"}}}),
reconcile("Certificate"; ["certificate"]; {tls:{certificate:{"@type":"File",filePath:"/certificates/current/fullchain.pem"},
  privateKey:{"@type":"File",filePath:"/certificates/current/privkey.pem"}}}),
update("SystemSettings"; {defaultHostname:$hostname,defaultDomainId:"#domain",defaultCertificateId:"#tls",
  includeSecrets:false,proxyTrustedNetworks:{},maxConnections:512,
  services:{smtp:{hostname:$hostname,cleartext:false},imap:{hostname:$hostname,cleartext:false},
    jmap:{hostname:$hostname,cleartext:false}},mailExchangers:{}}),
reconcile("NetworkListener"; ["name"]; {
  smtp:listener("tmail-smtp";1465;"smtp";{($proxy + "/32"):true}),
  imap:listener("tmail-imap";1993;"imap";{($proxy + "/32"):true}),
  admin:listener("tmail-admin";8443;"http";{($proxy + "/32"):true}),
  maintenance:listener("tmail-maintenance";8444;"http";{})
}),
reconcile("Application"; ["description"]; {webui:{description:"tmail bundled WebUI",enable:true,
  resourceUrl:"file:///opt/tmail/webui.zip",urlPrefix:{"/admin":true,"/account":true},
  autoUpdateInterval:315360000000,unpackDirectory:"/var/cache/tmail/webui"}}),
reconcile("Tracer"; "*"; {console:{"@type":"Stdout",enable:true,level:"info",ansi:false,
  eventsPolicy:"include",events:{"server.startup":true,"server.shutdown":true,"server.startup-error":true,
    "network.bind-error":true,"network.listen-error":true,"tls.no-certificates-available":true,
    "tls.expired-certificate-removed":true}}}),
update("Http"; {clientIpSource:"peer",enableHsts:true,usePermissiveCors:false,redirectRoot:"/admin"}),
update("Imap"; {allowPlainTextAuth:false,maxConcurrentConnections:16,maxRequestSize:10485760}),
update("Sharing"; {allowDirectoryQueries:false}),

update("MtaStageAuth"; {require:expr("true"),mustMatchSender:expr("true"),
  saslMechanisms:{"else":"false",match:{"0":{"if":"is_tls",then:"[plain, login]"}}}}),
update("MtaStageMail"; {isSenderAllowed:expr("!is_empty(authenticated_as) && sender == authenticated_as"),
  rewrite:expr("false"),script:expr("false")}),
update("MtaStageRcpt"; {maxRecipients:expr("20"),allowRelaying:expr("false"),rewrite:expr("false"),
  script:{"else":"'tmail-deny-peer'",match:{"0":{
    "if":"rcpt_domain == 'tmail.internal' && (authenticated_as == 'owner@tmail.internal' || rcpt == 'owner@tmail.internal' || key_exists('tmail-peers', authenticated_as + '|' + rcpt))",
    then:"false"}}}}),
upsert("SieveSystemScript"; ["name"]; {
  peerScript:{name:"tmail-deny-peer",isActive:true,contents:"require [\"reject\"]; reject \"550 5.7.1 Recipient not permitted by tmail policy\";"},
  fromScript:{name:"tmail-check-from",isActive:true,contents:$fromScript}
}),
update("MtaStageData"; {maxMessageSize:expr("10485760"),enableSpamFilter:expr("false"),
  dkimSignDomain:expr("false"),script:expr("'tmail-check-from'"),
  addAuthResultsHeader:expr("false"),addReceivedSpfHeader:expr("false"),
  addDateHeader:expr("true"),addMessageIdHeader:expr("true")}),
reconcile("MtaInboundThrottle"; ["description"]; {submission:{description:"tmail 60 submissions per minute",
  enable:true,key:{authenticatedAs:true},match:expr("!is_empty(authenticated_as)"),rate:{count:60,period:60000}}}),
reconcile("MtaRoute"; ["name"]; {local:{"@type":"Local",name:"local"}}),
update("MtaOutboundStrategy"; {route:expr("'local'"),schedule:expr("'local'")}),
update("SieveUserInterpreter"; {maxRedirects:0,maxOutMessages:0,allowedNotifyUris:{},dkimSignDomain:expr("false")}),
update("SieveSystemInterpreter"; {maxRedirects:0,maxOutMessages:0,dkimSignDomain:expr("false")}),
update("SenderAuth"; {arcVerify:expr("disable"),dkimVerify:expr("disable"),dmarcVerify:expr("disable"),
  reverseIpVerify:expr("disable"),spfEhloVerify:expr("disable"),spfFromVerify:expr("disable")}),
update("SpamSettings"; {enable:false,spamFilterRulesUrl:null}),
update("SpamPyzor"; {enable:false}),
update("Asn"; {"@type":"Disabled"}),
update("Metrics"; {openTelemetry:{"@type":"Disabled"},prometheus:{"@type":"Disabled"},metricsPolicy:"include",metrics:{}}),
update("Encryption"; {gatewayEnable:false,harvestKeys:expr("false"),hkpServers:{},discoveryProxy:null}),
(["MtaHook","MtaMilter","WebHook","SpamDnsblServer","MailingList","SieveUserScript"][] |
  {"@type":"destroy",object:.,value:{}}),
update("DnsResolver"; {"@type":"Custom",servers:{"0":{address:"127.0.0.1",port:53,protocol:"udp"}},timeout:1000,attempts:1}),
update("ReportSettings"; {inboundReportAddresses:{}}),
update("DmarcReportSettings"; {aggregateSendFrequency:expr("false"),failureSendFrequency:expr("false")}),
update("TlsReportSettings"; {sendFrequency:expr("false")}),
update("SpfReportSettings"; {sendFrequency:expr("false")}),
update("DkimReportSettings"; {sendFrequency:expr("false")})
